//! The Tauri shell: a small, frameless, monochrome progress window that
//! streams stage updates from the background install/update task.

use std::path::PathBuf;
use std::sync::mpsc;
use std::time::Duration;

use marvi_bootstrap_core::{
    InstallConfig, InstallLog, NpmBuildRunner, UpdateConfig, install, run_update, state_dir,
};
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Listener};

use crate::cli::{Cli, Mode};

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct ProgressPayload {
    stage: String,
    /// How far along, 0-100.
    percent: u8,
}

/// Stage text to a percentage, in the order the stages actually happen.
///
/// The bar has to be real, and the only honest source of "real" here is which
/// step has started -- there is no byte count to divide. So each milestone is
/// a step that genuinely ran, and the numbers are spaced by how long each one
/// takes rather than evenly: `npm ci` and the build together are most of a
/// fifteen-minute install, so they get most of the bar. Anything between two
/// milestones holds at the lower one, which is why the log is there too.
///
/// Matched by prefix against the same strings the core emits. `stages_match_
/// what_the_core_emits` below is the guard against those drifting apart.
const MILESTONES: &[(&str, u8)] = &[
    ("waiting for Marvi OS to exit", 2),
    ("checking uv and Node", 4),
    ("installing uv", 6),
    ("installing Node", 10),
    ("cloning", 14),
    ("current commit", 14),
    ("updating to", 18),
    ("installing dependencies (npm ci)", 25),
    ("building (npm run build:unpack)", 55),
    ("activating installation", 95),
];

fn percent_for(stage: &str) -> Option<u8> {
    MILESTONES
        .iter()
        .find(|(prefix, _)| stage.starts_with(prefix))
        .map(|(_, percent)| *percent)
}

#[derive(Clone, Serialize)]
struct MetaPayload {
    mode: String,
    channel: String,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct AskGpuPayload {
    prompt: String,
}

#[derive(Clone, Deserialize)]
#[serde(rename_all = "camelCase")]
struct GpuAnswer {
    use_gpu: bool,
}

/// Long enough to read the question and decide; short enough that an installer
/// left running overnight still finishes. Timing out means "not answered",
/// which leaves the choice to Marvi's own detection rather than guessing.
const ASK_TIMEOUT: Duration = Duration::from_secs(300);

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct DonePayload {
    status: String,
    message: String,
    from: Option<String>,
    to: Option<String>,
}

/// Launch the window and run the requested operation in the background.
pub fn run(args: Cli) {
    tauri::Builder::default()
        .setup(move |app| {
            let handle = app.handle().clone();
            std::thread::spawn(move || operate(&handle, args));
            Ok(())
        })
        .run(tauri::generate_context!())
        .expect("error while running Marvi Bootstrap");
}

/// Ask the window whether to use the GPU, and block until it answers.
///
/// Returns None when there is nothing to ask — no GPU, or no driver that can
/// drive the one that is there — and when the user simply does not answer.
fn ask_about_gpu(handle: &AppHandle, progress: &mut dyn FnMut(&str)) -> Option<bool> {
    let found = detect_gpu();
    let name = found?;
    progress(&format!("found {name}"));

    let (tx, rx) = mpsc::channel::<bool>();
    let id = handle.listen("gpu-answer", move |event| {
        if let Ok(answer) = serde_json::from_str::<GpuAnswer>(event.payload()) {
            let _ = tx.send(answer.use_gpu);
        }
    });
    let _ = handle.emit(
        "ask-gpu",
        AskGpuPayload {
            prompt: format!(
                "Found {name}. Use it for models that support it? Choosing CPU \
                 installs smaller packages, but voice and vision will be markedly \
                 slower."
            ),
        },
    );

    let answer = rx.recv_timeout(ASK_TIMEOUT).ok();
    handle.unlisten(id);
    match answer {
        Some(true) => progress("using the GPU"),
        Some(false) => progress("using the CPU"),
        None => progress("no answer; letting Marvi decide"),
    }
    answer
}

/// The name of a usable NVIDIA GPU, if `nvidia-smi` reports one.
///
/// Deliberately shallow: this only decides whether there is a question worth
/// asking. Marvi's own `marvi gpu` does the real detection, including whether
/// the driver actually works.
fn detect_gpu() -> Option<String> {
    let output = std::process::Command::new("nvidia-smi")
        .args(["--query-gpu=name", "--format=csv,noheader"])
        .output()
        .ok()?;
    if !output.status.success() {
        return None;
    }
    let name = String::from_utf8_lossy(&output.stdout)
        .lines()
        .next()?
        .trim()
        .to_string();
    (!name.is_empty()).then_some(name)
}

fn operate(handle: &AppHandle, args: Cli) {
    let _ = handle.emit("meta", MetaPayload {
        mode: format!("{:?}", args.mode).to_ascii_lowercase(),
        channel: args.channel.as_str().to_string(),
    });

    // Everything the window shows also goes to disk. A window that closes is
    // not a record, and an install that fails is exactly when one is needed.
    let mut log = InstallLog::open(
        &state_dir(),
        &format!("{:?}", args.mode).to_ascii_lowercase(),
    );
    let log_path = log.path().display().to_string();
    // Never goes backwards. Build output is forwarded through this same
    // closure, and a line of npm output that happens to start with an earlier
    // milestone would otherwise rewind the bar.
    let mut percent = 0u8;
    let mut progress = |stage: &str| {
        log.line(stage);
        percent = percent.max(percent_for(stage).unwrap_or(0));
        let _ = handle.emit("progress", ProgressPayload {
            stage: stage.to_string(),
            percent,
        });
    };

    let (status, message, from, to) = match args.mode {
        Mode::Install => {
            // Asked before the install starts, because the answer decides which
            // PyTorch build the Python step downloads, and getting that wrong
            // is a multi-gigabyte mistake rather than a slow one.
            let use_gpu = match args.use_gpu {
                Some(chosen) => Some(chosen),
                None => ask_about_gpu(handle, &mut progress),
            };
            let mut cfg = InstallConfig {
                install_root: PathBuf::from(&args.install_root),
                channel: args.channel,
                repo: args.repo.clone(),
                state_dir: state_dir(),
                relaunch_exe: args.relaunch_exe.clone().map(PathBuf::from),
                builder: Box::new(NpmBuildRunner::default()),
                provision_toolchain: true,
                use_gpu,
            };
            let out = install(&mut cfg, &mut progress);
            (out.status, out.message, None, out.to)
        }
        Mode::Update => {
            let mut cfg = UpdateConfig {
                install_root: PathBuf::from(&args.install_root),
                channel: args.channel,
                state_dir: state_dir(),
                desktop_pid: args.desktop_pid,
                relaunch_exe: args.relaunch_exe.clone().map(PathBuf::from),
                no_relaunch: args.no_relaunch,
                builder: Box::new(NpmBuildRunner::default()),
                provision_toolchain: true,
            };
            let out = run_update(&mut cfg, &mut progress);
            (out.status, out.message, out.from, out.to)
        }
        Mode::Check => unreachable!("check mode is handled headlessly in main"),
    };

    progress(&format!("=== {status}: {message} ==="));
    // Named in the window too, so the user knows where to look without having
    // to be told which folder Marvi keeps its logs in.
    if status != "ok" {
        progress(&format!("the full log is at {log_path}"));
    }
    let _ = handle.emit("done", DonePayload {
        status,
        message,
        from,
        to,
    });

    // No auto-close, on any outcome. It used to exit 1.5s after finishing,
    // which was long enough to see that something had appeared and not long
    // enough to read it -- so a failed install looked identical to a successful
    // one: a window that flashed and went away. The window now waits for the
    // Close button. Nothing depends on it exiting: `finish` has already cleared
    // the in-progress marker and relaunched Marvi by this point.
    handle.listen("close-window", |_| std::process::exit(0));
}

#[cfg(test)]
mod tests {
    use super::*;

    /// Every milestone string must still be emitted by the core, or the bar
    /// silently stops moving at whatever the last surviving one was. The core
    /// emits these with `progress("...")` or `progress(&format!("...` , so
    /// grepping the sources for the literal is enough to catch a rename.
    #[test]
    fn stages_match_what_the_core_emits() {
        let sources: String = ["install.rs", "update.rs", "toolchain.rs", "builder.rs"]
            .iter()
            .map(|name| {
                std::fs::read_to_string(
                    std::path::Path::new(env!("CARGO_MANIFEST_DIR"))
                        .join("../crates/core/src")
                        .join(name),
                )
                .unwrap_or_default()
            })
            .collect();

        for (prefix, _) in MILESTONES {
            assert!(
                sources.contains(prefix),
                "no core stage starts with {prefix:?}; the progress bar will stall"
            );
        }
    }

    #[test]
    fn the_bar_only_moves_forward() {
        let mut percent = 0u8;
        // A real sequence, including a line of build output that starts with an
        // earlier milestone's text.
        for stage in [
            "checking uv and Node",
            "installing dependencies (npm ci)",
            "building (npm run build:unpack)",
            "cloning something the build mentioned",
            "activating installation",
        ] {
            percent = percent.max(percent_for(stage).unwrap_or(0));
        }
        assert_eq!(percent, 95);
    }

    #[test]
    fn unknown_lines_do_not_move_the_bar() {
        assert_eq!(percent_for("added 412 packages in 38s"), None);
    }
}
