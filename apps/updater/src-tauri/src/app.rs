//! The Tauri shell: a small, frameless, monochrome progress window that
//! streams stage updates from the background install/update task.

use std::path::PathBuf;

use marvi_bootstrap_core::{
    InstallConfig, NpmBuildRunner, UpdateConfig, install, run_update, state_dir,
};
use serde::Serialize;
use tauri::{AppHandle, Emitter};

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

fn operate(handle: &AppHandle, args: Cli) {
    let _ = handle.emit("meta", MetaPayload {
        mode: format!("{:?}", args.mode).to_ascii_lowercase(),
        channel: args.channel.as_str().to_string(),
    });

    let mut progress = |stage: &str| {
        let _ = handle.emit("progress", ProgressPayload {
            stage: stage.to_string(),
        });
    };

    let (status, message, from, to) = match args.mode {
        Mode::Install => {
            let mut cfg = InstallConfig {
                install_root: PathBuf::from(&args.install_root),
                channel: args.channel,
                repo: args.repo.clone(),
                state_dir: state_dir(),
                relaunch_exe: args.relaunch_exe.clone().map(PathBuf::from),
                builder: Box::new(NpmBuildRunner::default()),
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
            };
            let out = run_update(&mut cfg, &mut progress);
            (out.status, out.message, out.from, out.to)
        }
        Mode::Check => unreachable!("check mode is handled headlessly in main"),
    };

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
