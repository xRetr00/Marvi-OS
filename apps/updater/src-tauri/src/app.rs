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
    let mut progress = |stage: &str| {
        log.line(stage);
        let _ = handle.emit("progress", ProgressPayload {
            stage: stage.to_string(),
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

    // Leave the final state visible for a beat, then exit. The relaunched (or
    // freshly launched) Electron app is already on its way.
    std::thread::sleep(std::time::Duration::from_millis(1500));
    std::process::exit(0);
}
