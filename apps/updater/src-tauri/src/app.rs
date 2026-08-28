//! The Tauri shell: a small, frameless, monochrome progress window that
//! streams stage updates from the background install/update task.

use std::path::PathBuf;
use std::sync::mpsc;
use std::time::Duration;

use marvi_bootstrap_core::{
    install, run_update, state_dir, InstallConfig, InstallLog, NpmBuildRunner, UpdateConfig,
};
use serde::{Deserialize, Serialize};
use tauri::{AppHandle, Emitter, Listener};

use crate::cli::{Cli, Mode};

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct ProgressPayload {
    stage_id: String,
    title: String,
    /// How far along, 0-100.
    percent: u8,
}

#[derive(Clone, Serialize)]
struct LogPayload {
    line: String,
}

#[derive(Clone, Serialize)]
#[serde(rename_all = "camelCase")]
struct StageInfo {
    id: &'static str,
    title: &'static str,
    percent: u8,
}

#[derive(Clone, Copy)]
struct Milestone {
    prefix: &'static str,
    stage_id: &'static str,
    title: &'static str,
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
const MILESTONES: &[Milestone] = &[
    Milestone {
        prefix: "waiting for Marvi OS to exit",
        stage_id: "handoff",
        title: "Closing Marvi OS",
        percent: 4,
    },
    Milestone {
        prefix: "cloning",
        stage_id: "source",
        title: "Downloading Marvi OS",
        percent: 10,
    },
    Milestone {
        prefix: "current commit",
        stage_id: "source",
        title: "Checking installed version",
        percent: 10,
    },
    Milestone {
        prefix: "updating to",
        stage_id: "source",
        title: "Downloading latest changes",
        percent: 18,
    },
    Milestone {
        prefix: "checking uv and Node",
        stage_id: "toolchain",
        title: "Checking system tools",
        percent: 22,
    },
    Milestone {
        prefix: "installing uv",
        stage_id: "toolchain",
        title: "Preparing system tools",
        percent: 25,
    },
    Milestone {
        prefix: "installing Node",
        stage_id: "toolchain",
        title: "Preparing system tools",
        percent: 28,
    },
    Milestone {
        prefix: "installing dependencies (npm ci)",
        stage_id: "dependencies",
        title: "Installing dependencies",
        percent: 32,
    },
    Milestone {
        prefix: "building (npm run build:unpack)",
        stage_id: "build",
        title: "Building desktop app",
        percent: 62,
    },
    Milestone {
        prefix: "activating installation",
        stage_id: "activate",
        title: "Activating installation",
        percent: 96,
    },
];

fn milestone_for(line: &str) -> Option<Milestone> {
    MILESTONES
        .iter()
        .find(|item| line.starts_with(item.prefix))
        .copied()
}

#[derive(Clone, Serialize)]
struct MetaPayload {
    mode: String,
    channel: String,
    stages: Vec<StageInfo>,
}

fn stages_for(mode: Mode) -> Vec<StageInfo> {
    let mut stages = Vec::new();
    if mode == Mode::Update {
        stages.push(StageInfo {
            id: "handoff",
            title: "Closing Marvi OS",
            percent: 4,
        });
    }
    stages.extend([
        StageInfo {
            id: "source",
            title: if mode == Mode::Install {
                "Downloading Marvi OS"
            } else {
                "Downloading latest changes"
            },
            percent: 18,
        },
        StageInfo {
            id: "toolchain",
            title: "Checking system tools",
            percent: 28,
        },
        StageInfo {
            id: "dependencies",
            title: "Installing dependencies",
            percent: 32,
        },
        StageInfo {
            id: "build",
            title: "Building desktop app",
            percent: 62,
        },
        StageInfo {
            id: "activate",
            title: "Activating installation",
            percent: 96,
        },
    ]);
    stages
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
const SUCCESS_CLOSE_DELAY: Duration = Duration::from_millis(1800);

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
    // Register before work begins. A failure must always remain dismissible,
    // including if it happens immediately during preflight.
    handle.listen("close-window", |_| std::process::exit(0));

    // The renderer subscribes asynchronously. Waiting for its ready signal
    // prevents the meta event (and the channel label with it) from being lost
    // during WebView startup.
    let (ready_tx, ready_rx) = mpsc::channel::<()>();
    let ready_id = handle.listen("ui-ready", move |_| {
        let _ = ready_tx.send(());
    });
    let _ = ready_rx.recv_timeout(Duration::from_secs(3));
    handle.unlisten(ready_id);

    let _ = handle.emit(
        "meta",
        MetaPayload {
            mode: format!("{:?}", args.mode).to_ascii_lowercase(),
            channel: args.channel.as_str().to_string(),
            stages: stages_for(args.mode),
        },
    );

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
    let mut progress = |line: &str| {
        log.line(line);
        let _ = handle.emit(
            "log",
            LogPayload {
                line: line.to_string(),
            },
        );
        if let Some(milestone) = milestone_for(line) {
            percent = percent.max(milestone.percent);
            let _ = handle.emit(
                "progress",
                ProgressPayload {
                    stage_id: milestone.stage_id.to_string(),
                    title: milestone.title.to_string(),
                    percent,
                },
            );
        }
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
    let _ = handle.emit(
        "done",
        DonePayload {
            status: status.clone(),
            message,
            from,
            to,
        },
    );

    // Only a verified success closes itself. Failures, skips, and aborts stay
    // visible until explicitly dismissed so diagnostics are never hidden.
    if let Some(delay) = auto_close_delay(&status) {
        std::thread::sleep(delay);
        std::process::exit(0);
    }
}

fn auto_close_delay(status: &str) -> Option<Duration> {
    (status == "ok").then_some(SUCCESS_CLOSE_DELAY)
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

        for milestone in MILESTONES {
            assert!(
                sources.contains(milestone.prefix),
                "no core stage starts with {:?}; the progress bar will stall",
                milestone.prefix
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
            percent = percent.max(milestone_for(stage).map(|item| item.percent).unwrap_or(0));
        }
        assert_eq!(percent, 96);
    }

    #[test]
    fn unknown_lines_do_not_move_the_bar() {
        assert!(milestone_for("added 412 packages in 38s").is_none());
    }

    #[test]
    fn logs_cannot_become_stages() {
        let line = "npm warn deprecated inflight@1.0.6";
        assert!(milestone_for(line).is_none());
        assert!(milestone_for("installing dependencies (npm ci)").is_some());
    }

    #[test]
    fn update_manifest_has_handoff_and_install_does_not() {
        assert_eq!(stages_for(Mode::Update).first().unwrap().id, "handoff");
        assert!(stages_for(Mode::Install)
            .iter()
            .all(|stage| stage.id != "handoff"));
    }

    #[test]
    fn only_success_auto_closes() {
        assert_eq!(auto_close_delay("ok"), Some(SUCCESS_CLOSE_DELAY));
        for status in ["failed", "aborted", "skipped"] {
            assert_eq!(auto_close_delay(status), None, "{status} must stay open");
        }
    }
}
