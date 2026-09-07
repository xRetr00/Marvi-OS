#![cfg_attr(windows, windows_subsystem = "windows")]

//! Marvi's wake word, as a program rather than a Python process.
//!
//! It had been `pythonw.exe -m marvi_agent.wake_daemon`: a windowless
//! interpreter, started by the desktop, holding a microphone open all day. That
//! shape produced most of this feature's bugs — it died without anybody
//! noticing, it could not be seen or stopped, and "is it running?" was answered
//! by reading a heartbeat file and guessing at it.
//!
//! So: one executable, one job. A tray icon you can see and quit, an autostart
//! entry it owns itself, and the same `wake.json` the Gateway already reads —
//! the listener changed language and `/voice/wake` did not change at all.
//!
//! ## Modes
//!
//! Default is to listen. `--score <file>` reads raw 16-bit mono PCM and prints
//! one score per hop, which is how the port was checked against
//! `livekit.wakeword` — see `tests/parity.rs`. `--autostart on|off` writes the
//! Run key and exits, for the desktop's settings toggle.

use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use marvi_wake_host::audio;
use marvi_wake_host::autostart;
use marvi_wake_host::detector::{Detector, HOP_SAMPLES};
use marvi_wake_host::state::{self, State, HEARTBEAT};

/// One "Marvi" is one join. Without this the word stays in the two-second
/// window for its whole length and fires four times.
const DEBOUNCE: Duration = Duration::from_secs(4);
const DEFAULT_THRESHOLD: f32 = 0.5;
const AUTO_RESTART_SETTING: &str = "MARVI_WAKE_AUTO_RESTART";

fn auto_restart_enabled() -> bool {
    !matches!(
        marvi_wake_host::settings::get(AUTO_RESTART_SETTING)
            .trim()
            .to_ascii_lowercase()
            .as_str(),
        "0" | "false" | "no" | "off"
    )
}

fn models_dir() -> PathBuf {
    // Beside the executable when installed, in the crate while developing. The
    // same resolution the pet host uses, so one binary runs from either place
    // without a launcher deciding for it.
    let beside = std::env::current_exe()
        .ok()
        .and_then(|exe| exe.parent().map(|dir| dir.join("models")));
    match beside {
        Some(path) if path.join("marvi.onnx").is_file() => path,
        _ => Path::new(env!("CARGO_MANIFEST_DIR")).join("models"),
    }
}

/// How to reach Marvi, running or not.
///
/// `--wake` rather than a bespoke channel: it is the same argument either way,
/// and Electron's single-instance lock decides which of the two it means —
/// start her, or tell the running one to join.
fn packaged_app_command(listener: &Path) -> Option<PathBuf> {
    listener
        .parent()?
        .parent()?
        .parent()
        .map(|dir| dir.join("Marvi-OS.exe"))
}

fn app_command() -> PathBuf {
    if let Ok(explicit) = std::env::var("MARVI_APP_COMMAND") {
        if !explicit.trim().is_empty() {
            return PathBuf::from(explicit.trim());
        }
    }
    if let Ok(root) = std::env::var("MARVI_INSTALL_ROOT") {
        if !root.trim().is_empty() {
            return PathBuf::from(root.trim()).join("apps/desktop/dist/win-unpacked/Marvi-OS.exe");
        }
    }
    // Installed under `resources/wake-host`, three levels below the desktop
    // executable. A login-started listener has no MARVI_APP_COMMAND from
    // Electron, so this fallback is the normal hands-free launch path. It used
    // to climb only to `resources` and use the old `Marvi.exe` name, making a
    // successful detection look like a listener crash because nothing opened.
    let installed = std::env::current_exe()
        .ok()
        .and_then(|exe| packaged_app_command(&exe));
    match installed {
        Some(path) if path.is_file() => path,
        _ => PathBuf::from("Marvi-OS.exe"),
    }
}

#[cfg(test)]
mod app_command_tests {
    use super::packaged_app_command;
    use std::path::Path;

    #[test]
    fn a_packaged_listener_finds_the_current_desktop_executable() {
        let listener = Path::new(
            r"C:\Marvi\apps\desktop\dist\win-unpacked\resources\wake-host\marvi-wake-host.exe",
        );
        assert_eq!(
            packaged_app_command(listener).unwrap(),
            Path::new(r"C:\Marvi\apps\desktop\dist\win-unpacked\Marvi-OS.exe")
        );
    }
}

fn join(confidence: f32) {
    let command = app_command();
    eprintln!(
        "wake word heard ({confidence:.2}); starting {}",
        command.display()
    );
    let mut launch = std::process::Command::new(&command);
    launch.arg("--wake");
    #[cfg(windows)]
    {
        use std::os::windows::process::CommandExt;
        // Detached and windowless: this listener outlives any one run of the
        // app so it must not become its parent, and a console flashing up at
        // the sound of your own voice is its own kind of alarm.
        const DETACHED_PROCESS: u32 = 0x0000_0008;
        const CREATE_NO_WINDOW: u32 = 0x0800_0000;
        launch.creation_flags(DETACHED_PROCESS | CREATE_NO_WINDOW);
    }
    if let Err(error) = launch.spawn() {
        eprintln!("could not start the app: {error}");
    }
}

fn score_file(path: &str) -> Result<(), Box<dyn std::error::Error>> {
    let raw = std::fs::read(path)?;
    let samples: Vec<i16> = raw
        .chunks_exact(2)
        .map(|pair| i16::from_le_bytes([pair[0], pair[1]]))
        .collect();
    let mut detector = Detector::load(&models_dir())?;
    for hop in samples.chunks(HOP_SAMPLES) {
        match detector.push(hop)? {
            Some(score) => println!("{score:.6}"),
            None => println!("warming"),
        }
    }
    Ok(())
}

fn threshold() -> f32 {
    std::env::var("MARVI_WAKE_THRESHOLD")
        .ok()
        .and_then(|value| value.trim().parse::<f32>().ok())
        .filter(|value| *value > 0.0 && *value <= 1.0)
        .unwrap_or(DEFAULT_THRESHOLD)
}

/// Set by the tray when the chosen microphone changes.
///
/// Re-opening a stream rather than restarting the process, for one reason: a
/// restart has to get past the single-instance mutex the replacement would
/// find still held by the process that spawned it. Swapping the stream is also
/// most of a second faster and keeps the tray icon on screen throughout.
static SWITCH: std::sync::atomic::AtomicBool = std::sync::atomic::AtomicBool::new(false);

pub fn ask_for_a_new_microphone() {
    SWITCH.store(true, std::sync::atomic::Ordering::Relaxed);
}

fn switch_requested() -> bool {
    SWITCH.swap(false, std::sync::atomic::Ordering::Relaxed)
}

/// Wraps `State` so `wake.json` cannot be left saying `running: true` after
/// `listen` has actually stopped -- however it stopped.
///
/// Before this existed, the only place that wrote `running: false` was three
/// lines after the loop below, reached only by a clean `break`. A scoring
/// error propagated with `?` -- which used to be the only option here --
/// returned out of `listen` from the middle of the loop and skipped straight
/// past it, so the file went on claiming a dead listener was alive until the
/// Gateway's own staleness check caught up fifteen seconds later, or forever
/// if the process then exited before writing again. A `Drop` impl cannot be
/// skipped by an early return, and unwinds with it if this thread ever panics
/// instead -- which is the one exit this program cannot enumerate in advance.
struct Reporting(State);

impl std::ops::Deref for Reporting {
    type Target = State;
    fn deref(&self) -> &State {
        &self.0
    }
}

impl std::ops::DerefMut for Reporting {
    fn deref_mut(&mut self) -> &mut State {
        &mut self.0
    }
}

impl Drop for Reporting {
    fn drop(&mut self) {
        self.0.running = false;
        self.0.heartbeat = state::now();
        self.0.write();
    }
}

/// Listen until told to stop. `quit` is set by the tray.
fn listen(quit: &dyn Fn() -> bool) -> Result<(), Box<dyn std::error::Error>> {
    let started = state::now();
    let mut report = Reporting(State {
        pid: std::process::id(),
        started_at: started,
        devices: audio::microphones(),
        default_device: audio::default_microphone(),
        ..Default::default()
    });

    // From the environment when the desktop started this, from the settings
    // file when Windows did. A login-started listener inherits nothing, and
    // read only from the environment it opened the default microphone however
    // carefully another had been chosen.
    let wanted = marvi_wake_host::settings::get("MARVI_WAKE_DEVICE");
    let mut microphone = match audio::open(&wanted) {
        Ok(open) => open,
        Err(error) => {
            // Written down rather than only logged: the settings page shows
            // this, and "no usable microphone" is the one failure a user can
            // actually fix. The final write with `running: false` happens
            // when `report` drops on the way out, below.
            report.error = error.clone();
            return Err(error.into());
        }
    };
    eprintln!("listening on {}", microphone.name);

    let mut detector = Detector::load(&models_dir())?;
    let limit = threshold();
    let mut pending: Vec<i16> = Vec::with_capacity(HOP_SAMPLES);
    let mut last_beat = Instant::now() - HEARTBEAT;
    let mut last_fired: Option<Instant> = None;

    report.running = true;
    loop {
        if quit() {
            break;
        }
        if switch_requested() {
            let wanted = marvi_wake_host::settings::get("MARVI_WAKE_DEVICE");
            match audio::open(&wanted) {
                Ok(open) => {
                    eprintln!("switched to {}", open.name);
                    report.error.clear();
                    // The old stream is dropped here, which closes it. Half a
                    // second of samples from the previous microphone is still
                    // in `pending`; mixing two devices' audio inside one
                    // two-second window is a detection made of both.
                    microphone = open;
                    pending.clear();
                    match Detector::load(&models_dir()) {
                        Ok(fresh) => detector = fresh,
                        Err(error) => {
                            // Keep scoring with the detector already running
                            // rather than losing wake-word detection entirely
                            // because the models could not be reopened after a
                            // microphone switch -- the same "imperfect beats
                            // nothing" rule the fallback to the default
                            // microphone follows just above. The window it
                            // was mid-way through judging now mixes half a
                            // second of the old microphone with the new one,
                            // which is one bad detection window, not a dead
                            // listener.
                            eprintln!("could not reload the detector: {error}");
                            report.error = error.to_string();
                        }
                    }
                }
                Err(error) => {
                    // Keep listening on the one that works. A chosen device
                    // that cannot be opened must not leave Marvi deaf.
                    eprintln!("could not switch microphone: {error}");
                    report.error = error;
                }
            }
            report.heartbeat = state::now();
            report.write();
        }
        // Timed rather than blocking, so the tray's Quit is acted on within a
        // beat even when the microphone has gone quiet or gone away.
        match microphone.samples.recv_timeout(Duration::from_millis(500)) {
            Ok(block) => pending.extend_from_slice(&block),
            Err(std::sync::mpsc::RecvTimeoutError::Timeout) => {}
            Err(std::sync::mpsc::RecvTimeoutError::Disconnected) => {
                report.error = "the microphone stopped".into();
                break;
            }
        }
        while pending.len() >= HOP_SAMPLES {
            let hop: Vec<i16> = pending.drain(..HOP_SAMPLES).collect();
            match detector.push(&hop) {
                Ok(Some(score)) => {
                    // A later successful inference proves a transient error
                    // has cleared. Leaving the old text in wake.json would
                    // leave the tray M red forever over a healthy listener.
                    report.error.clear();
                    report.confidence = score;
                    let ready = last_fired.is_none_or(|at| at.elapsed() >= DEBOUNCE);
                    if score >= limit && ready {
                        last_fired = Some(Instant::now());
                        let at = state::now();
                        report.heard_at = Some(at);
                        report.heard_total += 1;
                        // The score *at the firing*, before the next hop
                        // overwrites `confidence` with the silence after it.
                        report.heard_confidence = Some(score);
                        report.recent.insert(
                            0,
                            state::Detection {
                                at,
                                confidence: score,
                            },
                        );
                        report.recent.truncate(state::RECENT_DETECTIONS);
                        report.heartbeat = state::now();
                        report.write();
                        join(score);
                    }
                }
                // Not "heard nothing" -- "cannot say yet". See `Detector::push`.
                Ok(None) => {
                    report.error.clear();
                }
                Err(error) => {
                    // A single bad hop -- transient ONNX Runtime trouble, not
                    // a structural failure -- must not end wake-word detection
                    // for the rest of this process's life. This used to be
                    // `detector.push(&hop)?`, which returned out of `listen`
                    // on the first inference error and left the tray's
                    // "listening for her name" tooltip on screen over a
                    // thread that had quietly ended. Reported instead, and
                    // the loop moves on to the next hop.
                    eprintln!("scoring error: {error}");
                    report.error = error.to_string();
                }
            }
        }
        if last_beat.elapsed() >= HEARTBEAT {
            last_beat = Instant::now();
            report.heartbeat = state::now();
            report.write();
        }
    }

    // `report` drops here, which writes `running: false` -- see `Reporting`.
    Ok(())
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let arguments: Vec<String> = std::env::args().collect();

    if let Some(index) = arguments.iter().position(|a| a == "--score") {
        let path = arguments.get(index + 1).ok_or("--score needs a file")?;
        return score_file(path);
    }
    if let Some(index) = arguments.iter().position(|a| a == "--autostart") {
        match arguments.get(index + 1).map(String::as_str) {
            // Asked as well as set, because the settings toggle has to render
            // the current state and the registry is the only thing that knows.
            Some("status") => println!("{}", if autostart::registered() { "on" } else { "off" }),
            Some("on") => println!("{}", if autostart::set(true) { "on" } else { "failed" }),
            _ => println!(
                "{}",
                if autostart::set(false) {
                    "off"
                } else {
                    "failed"
                }
            ),
        }
        return Ok(());
    }
    if arguments.iter().any(|a| a == "--stop") {
        marvi_wake_host::state::request_stop();
        return Ok(());
    }
    if arguments.iter().any(|a| a == "--microphones") {
        for name in audio::microphones() {
            println!("{name}");
        }
        return Ok(());
    }

    // Nothing below this line opens the microphone until it is the only thing
    // that will be. Enabling from Settings starts one now and registers it for
    // login, so the second start is the normal case rather than the odd one.
    if !marvi_wake_host::takeover::only_instance() {
        eprintln!("another listener is already running");
        return Ok(());
    }
    if marvi_wake_host::takeover::take() {
        eprintln!("stopped the listener that was running before this one");
    }

    // A stop request belongs to the listener that observed it. A later,
    // explicit start must not inherit an old marker and immediately exit.
    marvi_wake_host::state::clear_stop_request();

    tray::run(listen)
}

/// The tray icon, and the message loop it needs.
///
/// The whole reason this is a program rather than a hidden process: something
/// you can see is running, and stop without opening Task Manager.
#[cfg(windows)]
mod tray {
    use std::sync::atomic::{AtomicBool, Ordering};

    use tray_icon::menu::{CheckMenuItem, Menu, MenuEvent, MenuItem, Submenu};
    use tray_icon::{Icon, TrayIconBuilder};
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        DispatchMessageW, PeekMessageW, TranslateMessage, MSG, PM_REMOVE,
    };

    static QUIT: AtomicBool = AtomicBool::new(false);

    const HEARD_GREEN_FOR: std::time::Duration = std::time::Duration::from_secs(6);

    #[derive(Clone, Copy, Debug, Eq, PartialEq)]
    enum TrayState {
        Listening,
        Armed,
        Error,
    }

    impl TrayState {
        fn rgb(self) -> [u8; 3] {
            match self {
                // Marvi's restrained status blue, success green, and danger
                // red. Color is paired with the tooltip below, never the only
                // indication of state.
                Self::Listening => [0x14, 0x7E, 0xC1],
                Self::Armed => [0x4D, 0xAA, 0x72],
                Self::Error => [0xD8, 0x5B, 0x5B],
            }
        }

        fn tooltip(self, detail: &str) -> String {
            match self {
                Self::Listening => "Marvi wake word — listening".into(),
                Self::Armed => "Marvi wake word — heard “Marvi”".into(),
                Self::Error if !detail.trim().is_empty() => {
                    format!("Marvi wake word — error: {}", detail.trim())
                }
                Self::Error => "Marvi wake word — error; restarting".into(),
            }
        }
    }

    fn visual_state(
        worker_running: bool,
        report: Option<&marvi_wake_host::state::State>,
    ) -> TrayState {
        if !worker_running || report.is_some_and(|state| !state.error.trim().is_empty()) {
            return TrayState::Error;
        }
        let recently_heard = report.and_then(|state| state.heard_at).is_some_and(|at| {
            let age = marvi_wake_host::state::now() - at;
            age >= 0.0 && age <= HEARD_GREEN_FOR.as_secs_f64()
        });
        if recently_heard {
            TrayState::Armed
        } else {
            TrayState::Listening
        }
    }

    fn distance_to_segment(px: f32, py: f32, ax: f32, ay: f32, bx: f32, by: f32) -> f32 {
        let dx = bx - ax;
        let dy = by - ay;
        let length_squared = dx * dx + dy * dy;
        let t = if length_squared == 0.0 {
            0.0
        } else {
            (((px - ax) * dx + (py - ay) * dy) / length_squared).clamp(0.0, 1.0)
        };
        ((px - (ax + t * dx)).powi(2) + (py - (ay + t * dy)).powi(2)).sqrt()
    }

    fn icon_rgba(state: TrayState) -> Vec<u8> {
        const SIZE: u32 = 32;
        const STROKE_RADIUS: f32 = 2.35;
        const EDGE: f32 = 1.0;
        let color = state.rgb();
        let strokes = [
            (6.5, 26.0, 6.5, 6.0),
            (6.5, 6.0, 16.0, 18.0),
            (16.0, 18.0, 25.5, 6.0),
            (25.5, 6.0, 25.5, 26.0),
        ];
        let mut rgba = Vec::with_capacity((SIZE * SIZE * 4) as usize);
        for y in 0..SIZE {
            for x in 0..SIZE {
                let px = x as f32 + 0.5;
                let py = y as f32 + 0.5;
                let distance = strokes
                    .iter()
                    .map(|&(ax, ay, bx, by)| distance_to_segment(px, py, ax, ay, bx, by))
                    .fold(f32::INFINITY, f32::min);
                let alpha = ((STROKE_RADIUS + EDGE - distance).clamp(0.0, EDGE) * 255.0) as u8;
                rgba.extend_from_slice(&[color[0], color[1], color[2], alpha]);
            }
        }
        rgba
    }

    /// A purpose-drawn M stays readable after Windows scales the 32 px tray
    /// asset down to 16 px. It is generated locally and changes color with the
    /// listener state; no asset or font can go missing at login.
    fn icon(state: TrayState) -> Option<Icon> {
        const SIZE: u32 = 32;
        Icon::from_rgba(icon_rgba(state), SIZE, SIZE).ok()
    }

    pub fn run(
        listen: fn(&dyn Fn() -> bool) -> Result<(), Box<dyn std::error::Error>>,
    ) -> Result<(), Box<dyn std::error::Error>> {
        let menu = Menu::new();
        let autostart_item = MenuItem::new(
            if marvi_wake_host::autostart::registered() {
                "Start with Windows ✓"
            } else {
                "Start with Windows"
            },
            true,
            None,
        );
        // The microphone lives here rather than in Marvi's settings page,
        // because this is the program that opens it. The page listed what
        // PortAudio could see and this can only open what cpal can, so the two
        // lists disagreed and choosing from the wrong one silently fell back
        // to the default.
        let chosen = marvi_wake_host::settings::get("MARVI_WAKE_DEVICE");
        let devices = marvi_wake_host::audio::microphones();
        let microphones = Submenu::new("Microphone", true);
        let default_item = CheckMenuItem::new("System default", true, chosen.is_empty(), None);
        microphones.append(&default_item)?;
        let mut device_items = Vec::with_capacity(devices.len());
        for name in &devices {
            // Names arrive with newlines and driver paths in the middle of
            // them on Bluetooth headsets; a menu item is one line either way.
            let label: String = name.split_whitespace().collect::<Vec<_>>().join(" ");
            let item = CheckMenuItem::new(&label, true, *name == chosen, None);
            microphones.append(&item)?;
            device_items.push((item, name.clone()));
        }

        let quit_item = MenuItem::new("Quit", true, None);
        menu.append(&microphones)?;
        menu.append(&autostart_item)?;
        menu.append(&quit_item)?;

        let initial_state = TrayState::Listening;
        let tray = TrayIconBuilder::new()
            .with_tooltip(initial_state.tooltip(""))
            .with_menu(Box::new(menu))
            .with_icon(icon(initial_state).ok_or("could not build the tray icon")?)
            .build()?;

        let quit_id = quit_item.id().clone();
        let autostart_id = autostart_item.id().clone();
        let default_id = default_item.id().clone();

        fn spawn_worker(
            listen: fn(&dyn Fn() -> bool) -> Result<(), Box<dyn std::error::Error>>,
        ) -> std::thread::JoinHandle<()> {
            std::thread::spawn(move || {
                if let Err(error) = listen(&|| QUIT.load(Ordering::Relaxed)) {
                    eprintln!("wake word stopped: {error}");
                }
            })
        }

        // The listener runs on its own thread; this one pumps messages, which
        // on Windows is what keeps a tray icon alive at all. `worker` is
        // `None` while a delayed retry is pending, or while the user-selected
        // auto-restart setting is off. The tray remains responsive either way.
        let mut worker = Some(spawn_worker(listen));
        let mut worker_started = std::time::Instant::now();
        let mut backoff = marvi_wake_host::restart::Backoff::new();
        let mut restart_at: Option<std::time::Instant> = None;
        let mut shown_state = initial_state;
        let mut visual_poll = std::time::Instant::now() - std::time::Duration::from_secs(1);

        let receiver = MenuEvent::receiver();
        while !QUIT.load(Ordering::Relaxed) {
            if marvi_wake_host::state::stop_requested() {
                marvi_wake_host::state::clear_stop_request();
                QUIT.store(true, Ordering::Relaxed);
                continue;
            }
            // `listen` does not normally return early -- see `Reporting` and
            // the per-hop error handling in `main.rs` -- but this is the net
            // under that net: whatever still ends the thread (a panic inside
            // the ONNX runtime's own C++, which no amount of `Result` handling
            // on this side can catch), the tray notices within a beat instead
            // of sitting on a dead microphone with a tooltip that still claims
            // to be listening.
            if let Some(handle) = &worker {
                if handle.is_finished() && !QUIT.load(Ordering::Relaxed) {
                    let delay = backoff.delay(worker_started.elapsed());
                    worker = None;
                    if super::auto_restart_enabled() {
                        eprintln!("listener thread ended; restarting in {}s", delay.as_secs());
                        restart_at = Some(std::time::Instant::now() + delay);
                    } else {
                        eprintln!("listener thread ended; automatic restart is off");
                        restart_at = None;
                    }
                }
            }
            if worker.is_none() && super::auto_restart_enabled() {
                let ready = restart_at.is_none_or(|at| std::time::Instant::now() >= at);
                if ready {
                    worker = Some(spawn_worker(listen));
                    worker_started = std::time::Instant::now();
                    restart_at = None;
                }
            }
            if visual_poll.elapsed() >= std::time::Duration::from_millis(500) {
                visual_poll = std::time::Instant::now();
                let report = marvi_wake_host::state::read();
                let next = visual_state(worker.is_some(), report.as_ref());
                if next != shown_state {
                    tray.set_icon(icon(next))?;
                    tray.set_tooltip(Some(
                        next.tooltip(
                            report
                                .as_ref()
                                .map(|state| state.error.as_str())
                                .unwrap_or(""),
                        ),
                    ))?;
                    shown_state = next;
                }
            }
            let mut message: MSG = unsafe { std::mem::zeroed() };
            while unsafe { PeekMessageW(&mut message, std::ptr::null_mut(), 0, 0, PM_REMOVE) } != 0
            {
                unsafe {
                    TranslateMessage(&message);
                    DispatchMessageW(&message);
                }
            }
            while let Ok(event) = receiver.try_recv() {
                if event.id == quit_id {
                    QUIT.store(true, Ordering::Relaxed);
                } else if event.id == default_id
                    || device_items.iter().any(|(i, _)| *i.id() == event.id)
                {
                    let picked = if event.id == default_id {
                        String::new()
                    } else {
                        device_items
                            .iter()
                            .find(|(item, _)| *item.id() == event.id)
                            .map(|(_, name)| name.clone())
                            .unwrap_or_default()
                    };
                    // Saved where the settings page keeps it, then acted on
                    // now: a choice that only takes effect at the next login
                    // is one you cannot tell you made.
                    marvi_wake_host::settings::set("MARVI_WAKE_DEVICE", &picked);
                    super::ask_for_a_new_microphone();
                    // The click already toggled the item it landed on. Every
                    // other one has to be cleared, or two microphones show a
                    // tick and the menu stops meaning anything.
                    default_item.set_checked(picked.is_empty());
                    for (item, name) in &device_items {
                        item.set_checked(*name == picked);
                    }
                } else if event.id == autostart_id {
                    let now_on = !marvi_wake_host::autostart::registered();
                    marvi_wake_host::autostart::set(now_on);
                    autostart_item.set_text(if now_on {
                        "Start with Windows ✓"
                    } else {
                        "Start with Windows"
                    });
                }
            }
            std::thread::sleep(std::time::Duration::from_millis(100));
        }
        if let Some(handle) = worker {
            let _ = handle.join();
        }
        Ok(())
    }

    #[cfg(test)]
    mod tests {
        use super::*;

        #[test]
        fn the_tray_mark_is_an_m_in_semantic_colors() {
            for (state, color) in [
                (TrayState::Listening, [0x14, 0x7E, 0xC1]),
                (TrayState::Armed, [0x4D, 0xAA, 0x72]),
                (TrayState::Error, [0xD8, 0x5B, 0x5B]),
            ] {
                let pixels = icon_rgba(state);
                assert_eq!(pixels.len(), 32 * 32 * 4);
                assert!(pixels
                    .chunks_exact(4)
                    .any(|pixel| { pixel[0..3] == color && pixel[3] == 255 }));
                // The old yellow ring must not survive in any state.
                assert!(!pixels
                    .chunks_exact(4)
                    .any(|pixel| { pixel[0..3] == [0xE8, 0x8C, 0x3A] && pixel[3] != 0 }));
            }
        }

        #[test]
        fn visual_state_has_text_equivalents_for_color() {
            assert!(TrayState::Listening.tooltip("").contains("listening"));
            assert!(TrayState::Armed.tooltip("").contains("heard"));
            assert!(TrayState::Error
                .tooltip("microphone stopped")
                .contains("microphone stopped"));
        }

        #[test]
        fn visual_state_prioritizes_errors_then_recent_wake_detection() {
            let mut report = marvi_wake_host::state::State::default();

            assert_eq!(visual_state(true, Some(&report)), TrayState::Listening);

            report.heard_at = Some(marvi_wake_host::state::now());
            assert_eq!(visual_state(true, Some(&report)), TrayState::Armed);

            report.error = "microphone stopped".into();
            assert_eq!(visual_state(true, Some(&report)), TrayState::Error);

            report.error.clear();
            assert_eq!(visual_state(false, Some(&report)), TrayState::Error);
        }
    }
}

#[cfg(not(windows))]
mod tray {
    use std::sync::atomic::AtomicBool;

    static QUIT: AtomicBool = AtomicBool::new(false);

    /// No tray off Windows. The listener still runs, which is what a developer
    /// on another platform actually needs from it.
    pub fn run(
        listen: fn(&dyn Fn() -> bool) -> Result<(), Box<dyn std::error::Error>>,
    ) -> Result<(), Box<dyn std::error::Error>> {
        listen(&|| QUIT.load(std::sync::atomic::Ordering::Relaxed))
    }
}
