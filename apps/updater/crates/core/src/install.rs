//! Bootstrap installer: clone the target release into a staging directory,
//! build it, then atomically swap it into place. A failed install deletes the
//! staging tree and leaves nothing half-installed.

use std::path::{Path, PathBuf};

use crate::builder::BuildRunner;
use crate::channels::Channel;
use crate::git::{self, SignatureStatus};
use crate::result::UpdateResult;
use crate::tags;
use crate::util::random_suffix;

/// The Node the desktop build is known to work with. Bumping this is how a
/// release asks for a newer toolchain.
pub const NODE_VERSION: &str = "v22.11.0";

pub struct InstallConfig {
    pub install_root: PathBuf,
    pub channel: Channel,
    pub repo: String,
    pub state_dir: PathBuf,
    pub relaunch_exe: Option<PathBuf>,
    pub builder: Box<dyn BuildRunner>,
}

#[derive(Debug, Clone)]
pub struct InstallOutcome {
    pub status: String,
    pub message: String,
    pub to: Option<String>,
    pub installed_at: PathBuf,
}

/// The target ref to clone for a channel.
fn target_ref(channel: Channel, repo: &str, cwd: &Path) -> Result<(String, Option<String>), String> {
    match channel {
        Channel::Dev => Ok(("main".to_string(), None)),
        Channel::Release => {
            let tags = git::ls_remote_url_tags(repo, cwd)
                .map_err(|e| format!("could not list release tags: {e}"))?;
            let (tag, _) = tags::latest(tags)
                .ok_or_else(|| "no release tags found on the remote".to_string())?;
            Ok((tag.clone(), Some(tag)))
        }
    }
}

/// Install Marvi OS into `install_root`.
pub fn install(cfg: &mut InstallConfig, progress: &mut dyn FnMut(&str)) -> InstallOutcome {
    let fail = |message: String| InstallOutcome {
        status: "failed".to_string(),
        message,
        to: None,
        installed_at: cfg.install_root.clone(),
    };

    // Held for the whole install. Someone who double-clicks the installer twice
    // would otherwise get two clones and two builds in the same directory.
    let _lock = match crate::singleton::acquire(&cfg.state_dir) {
        Ok(lock) => lock,
        Err(message) => return fail(message),
    };

    if cfg.install_root.exists() {
        let non_empty = std::fs::read_dir(&cfg.install_root)
            .map(|mut d| d.next().is_some())
            .unwrap_or(true);
        if non_empty {
            if git::is_work_tree(&cfg.install_root) {
                return fail(
                    "an existing Marvi OS checkout is already installed here; use update instead"
                        .to_string(),
                );
            }
            return fail(
                "the install directory already exists and is not empty; choose another location"
                    .to_string(),
            );
        }
        // Empty directory: fall through and install into it.
    }

    let parent = cfg
        .install_root
        .parent()
        .unwrap_or(Path::new("."))
        .to_path_buf();
    let name = cfg
        .install_root
        .file_name()
        .map(|n| n.to_string_lossy().to_string())
        .unwrap_or_else(|| "marvi-os".to_string());
    let staging = parent.join(format!("{name}.marvi-install-{}", random_suffix()));

    let cleanup = |staging: &Path| {
        let _ = std::fs::remove_dir_all(staging);
    };

    let (refname, tag) = match target_ref(cfg.channel, &cfg.repo, &parent) {
        Ok(v) => v,
        Err(e) => return fail(e),
    };
    progress(&format!("cloning {} ({})", cfg.repo, refname));

    if let Err(e) = git::clone(&cfg.repo, &refname, &staging) {
        cleanup(&staging);
        return fail(format!("clone failed: {e}"));
    }

    // Release integrity: a *bad* signature refuses the install; an *unsigned*
    // tag proceeds with a warning (the repository does not sign today).
    if let (Some(tag), Channel::Release) = (&tag, cfg.channel) {
        match git::verify_tag(&staging, tag) {
            Ok(SignatureStatus::Invalid(detail)) => {
                cleanup(&staging);
                return fail(format!("release tag {tag} has an invalid signature: {detail}"));
            }
            Ok(SignatureStatus::Unsigned) => {
                progress(&format!("warning: release tag {tag} is unsigned"));
            }
            _ => {}
        }
    }

    progress("building");
    let state = cfg.state_dir.clone();
    if let Err(e) = build_with_toolchain(&staging, Some(&state), &mut *cfg.builder, progress) {
        cleanup(&staging);
        return fail(e);
    }

    let to = git::current_commit(&staging).ok();
    progress("activating installation");

    // Atomically move staging into place. If install_root was an empty dir,
    // remove it first so the rename succeeds.
    if cfg.install_root.exists() {
        let _ = std::fs::remove_dir(&cfg.install_root);
    }
    if let Err(e) = std::fs::rename(&staging, &cfg.install_root) {
        cleanup(&staging);
        return fail(format!("could not activate the installation: {e}"));
    }

    let result = UpdateResult::new("ok", "Installed successfully.")
        .with_range("", to.as_deref().unwrap_or(""));
    let _ = crate::result::write_result(&cfg.state_dir, &result);

    // Make the bootstrap available to the installed app for future updates.
    install_self_to_bin(&cfg.state_dir);

    if let Some(exe) = &cfg.relaunch_exe {
        launch(exe);
    }

    InstallOutcome {
        status: "ok".to_string(),
        message: "Installed successfully.".to_string(),
        to,
        installed_at: cfg.install_root.clone(),
    }
}

/// Run the build and verify the runtime was produced.
/// Provision `uv` and Node, then build.
///
/// The check runs before **every** build, install or update, because a release
/// can need a newer toolchain than the one that installed the previous
/// release - and discovering that partway through `npm ci` is discovering it
/// too late to say anything useful.
///
/// The provisioned directories are prepended to `PATH` for the build itself.
/// A child process that cannot see the toolchain just installed is the exact
/// failure this is here to prevent.
pub(crate) fn build_with_toolchain(
    root: &Path,
    state_dir: Option<&Path>,
    builder: &mut dyn BuildRunner,
    progress: &mut dyn FnMut(&str),
) -> Result<(), String> {
    if let Some(state) = state_dir {
        progress("checking uv and Node");
        let extra = crate::toolchain::ensure_toolchain(state, NODE_VERSION, progress)?;
        if !extra.is_empty() {
            let merged = crate::toolchain::prepend_path(&extra, std::env::var("PATH").ok());
            // Safe here: single-threaded installer, set before any child runs.
            unsafe { std::env::set_var("PATH", merged) };
        }
    }
    builder.prepare(root, progress)?;
    if !smoke_ok(root) {
        return Err("build produced no runnable runtime (smoke test failed)".to_string());
    }
    Ok(())
}

/// Smoke test: the Electron runtime entrypoint must exist.
pub(crate) fn smoke_ok(root: &Path) -> bool {
    root.join("apps/desktop/out/main/index.js").is_file()
        || root
            .join("apps/desktop/dist/win-unpacked")
            .read_dir()
            .map(|mut d| d.next().is_some())
            .unwrap_or(false)
}

fn launch(exe: &Path) {
    if !exe.exists() {
        return;
    }
    let working_dir = exe.parent().unwrap_or(Path::new("."));
    let _ = std::process::Command::new(exe).current_dir(working_dir).spawn();
}

/// Copy the running bootstrap into `state_dir/bin` so the installed app can
/// hand off updates to it later. Skips the copy when already running from the
/// destination (a no-op that would otherwise fail on Windows).
fn install_self_to_bin(state_dir: &Path) {
    let Ok(exe) = std::env::current_exe() else {
        return;
    };
    let dir = state_dir.join("bin");
    let _ = std::fs::create_dir_all(&dir);
    let dest = dir.join("marvi-bootstrap.exe");
    if exe == dest {
        return;
    }
    let _ = std::fs::copy(&exe, &dest);
}
