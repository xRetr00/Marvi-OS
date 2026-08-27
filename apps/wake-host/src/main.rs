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
fn app_command() -> PathBuf {
    if let Ok(explicit) = std::env::var("MARVI_APP_COMMAND") {
        if !explicit.trim().is_empty() {
            return PathBuf::from(explicit.trim());
        }
    }
    if let Ok(root) = std::env::var("MARVI_INSTALL_ROOT") {
        if !root.trim().is_empty() {
            return PathBuf::from(root.trim()).join("Marvi.exe");
        }
    }
    // Installed beside this listener, which is where the packager puts both.
    std::env::current_exe()
        .ok()
        .and_then(|exe| exe.parent().and_then(|d| d.parent()).map(|d| d.join("Marvi.exe")))
        .unwrap_or_else(|| PathBuf::from("Marvi.exe"))
}

fn join(confidence: f32) {
    let command = app_command();
    eprintln!("wake word heard ({confidence:.2}); starting {}", command.display());
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

/// Listen until told to stop. `quit` is set by the tray.
fn listen(quit: &dyn Fn() -> bool) -> Result<(), Box<dyn std::error::Error>> {
    let started = state::now();
    let mut report = State { pid: std::process::id(), started_at: started, ..Default::default() };

    let wanted = std::env::var("MARVI_WAKE_DEVICE").unwrap_or_default();
    let microphone = match audio::open(&wanted) {
        Ok(open) => open,
        Err(error) => {
            // Written down rather than only logged: the settings page shows
            // this, and "no usable microphone" is the one failure a user can
            // actually fix.
            report.error = error.clone();
            report.heartbeat = state::now();
            report.write();
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
            if let Some(score) = detector.push(&hop)? {
                report.confidence = score;
                let ready = last_fired.is_none_or(|at| at.elapsed() >= DEBOUNCE);
                if score >= limit && ready {
                    last_fired = Some(Instant::now());
                    report.heard_at = Some(state::now());
                    report.heartbeat = state::now();
                    report.write();
                    join(score);
                }
            }
        }
        if last_beat.elapsed() >= HEARTBEAT {
            last_beat = Instant::now();
            report.heartbeat = state::now();
            report.write();
        }
    }

    report.running = false;
    report.heartbeat = state::now();
    report.write();
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
            _ => println!("{}", if autostart::set(false) { "off" } else { "failed" }),
        }
        return Ok(());
    }
    if arguments.iter().any(|a| a == "--microphones") {
        for name in audio::microphones() {
            println!("{name}");
        }
        return Ok(());
    }

    tray::run(listen)
}

/// The tray icon, and the message loop it needs.
///
/// The whole reason this is a program rather than a hidden process: something
/// you can see is running, and stop without opening Task Manager.
#[cfg(windows)]
mod tray {
    use std::sync::atomic::{AtomicBool, Ordering};

    use tray_icon::menu::{Menu, MenuEvent, MenuItem};
    use tray_icon::{Icon, TrayIconBuilder};
    use windows_sys::Win32::UI::WindowsAndMessaging::{
        DispatchMessageW, PeekMessageW, TranslateMessage, MSG, PM_REMOVE,
    };

    static QUIT: AtomicBool = AtomicBool::new(false);

    /// Marvi's mark, drawn rather than loaded: one file fewer to ship and to
    /// lose. A filled ring on transparent, which is what the orb reads as at
    /// sixteen pixels.
    fn icon() -> Option<Icon> {
        const SIZE: u32 = 32;
        let mut rgba = Vec::with_capacity((SIZE * SIZE * 4) as usize);
        let centre = (SIZE as f32 - 1.0) / 2.0;
        for y in 0..SIZE {
            for x in 0..SIZE {
                let distance =
                    ((x as f32 - centre).powi(2) + (y as f32 - centre).powi(2)).sqrt();
                // Antialiased edges, because a hard-edged circle at this size
                // reads as a polygon in the tray.
                let outer = (14.0 - distance).clamp(0.0, 1.0);
                let inner = (distance - 8.0).clamp(0.0, 1.0);
                let alpha = (outer * inner * 255.0) as u8;
                rgba.extend_from_slice(&[0xE8, 0x8C, 0x3A, alpha]);
            }
        }
        Icon::from_rgba(rgba, SIZE, SIZE).ok()
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
        let quit_item = MenuItem::new("Quit", true, None);
        menu.append(&autostart_item)?;
        menu.append(&quit_item)?;

        let _tray = TrayIconBuilder::new()
            .with_tooltip("Marvi — listening for her name")
            .with_menu(Box::new(menu))
            .with_icon(icon().ok_or("could not build the tray icon")?)
            .build()?;

        let quit_id = quit_item.id().clone();
        let autostart_id = autostart_item.id().clone();

        // The listener runs on its own thread; this one pumps messages, which
        // on Windows is what keeps a tray icon alive at all.
        let worker = std::thread::spawn(move || {
            if let Err(error) = listen(&|| QUIT.load(Ordering::Relaxed)) {
                eprintln!("wake word stopped: {error}");
            }
        });

        let receiver = MenuEvent::receiver();
        while !QUIT.load(Ordering::Relaxed) {
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
        let _ = worker.join();
        Ok(())
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
