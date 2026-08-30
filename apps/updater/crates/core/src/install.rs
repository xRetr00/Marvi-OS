//! Bootstrap installer: clone the target release into a staging directory,
//! build it, then atomically swap it into place. A failed install deletes the
//! staging tree and leaves nothing half-installed.

use std::path::{Path, PathBuf};

use crate::builder::BuildRunner;
use crate::channels::Channel;
use crate::git::{self, SignatureStatus};
use crate::result::UpdateResult;
use crate::tags;
use crate::util::{no_window, random_suffix};

/// The Node the desktop build is known to work with. Bumping this is how a
/// release asks for a newer toolchain.
/// The Node the installer provisions.
///
/// Must stay on the same major as `node-version` in `.github/workflows/release.yml`,
/// and CI guards that they agree — the point being that the Node a user gets is
/// the Node the release was gated on.
///
/// v22.11.0 shipped in v0.2.0 and could not build the app: every Electron and
/// Vite package requires `>=22.12.0`, and `electron-builder install-app-deps`
/// died with ERR_REQUIRE_ESM because `require()` of an ES module only works from
/// 22.12 onwards. It went unnoticed because every machine that built Marvi
/// already had a newer Node on PATH; provisioning our own is what exposed it.
pub const NODE_VERSION: &str = "v22.23.2";

/// How many times to try removing the previous packaged build. A killed
/// process can keep a file handle open for a moment after it is gone.
const BUILD_OUTPUT_ATTEMPTS: u32 = 5;

pub struct InstallConfig {
    pub install_root: PathBuf,
    pub channel: Channel,
    pub repo: String,
    pub state_dir: PathBuf,
    pub relaunch_exe: Option<PathBuf>,
    pub builder: Box<dyn BuildRunner>,
    /// False only in tests. Provisioning downloads ~100 MB of `uv` and Node,
    /// which a unit test has no business doing; the live test in
    /// `toolchain_live.rs` covers the real thing. Also gates the handoff, for
    /// the same reason: a test must not touch the user's PATH or Desktop.
    pub provision_toolchain: bool,
    /// The user's GPU answer, or None when they were not asked. Recorded before
    /// the Python environments are built, because it picks the PyTorch index
    /// and getting it wrong costs a multi-gigabyte reinstall.
    pub use_gpu: Option<bool>,
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
        Channel::Nightly => Ok(("main".to_string(), None)),
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
                // Repair rather than refuse. Running the installer over an
                // existing checkout used to fail with "use update instead",
                // which is useless advice when the reason you reached for the
                // installer is that updating from inside the app does not work
                // — the only way out was to uninstall first.
                //
                // An update is exactly what a repair is: fetch the target,
                // re-provision the toolchain, rebuild, roll back on failure.
                // The checkout and everything in the state directory survive.
                progress("Marvi is already installed here — repairing it instead");
                let mut update = crate::update::UpdateConfig {
                    install_root: cfg.install_root.clone(),
                    channel: cfg.channel,
                    state_dir: cfg.state_dir.clone(),
                    desktop_pid: None,
                    relaunch_exe: cfg.relaunch_exe.clone(),
                    no_relaunch: cfg.relaunch_exe.is_none(),
                    builder: std::mem::replace(&mut cfg.builder, Box::new(crate::builder::NpmBuildRunner::default())),
                    provision_toolchain: cfg.provision_toolchain,
                };
                let out = crate::update::run_update(&mut update, progress);
                // The repair path returns before the copy at the end of a
                // fresh install, so repairing with a newly downloaded
                // installer left the *old* bootstrap in place -- which meant
                // every fix to the updater itself never reached the machine
                // that needed it. Repair is the one path where the running
                // binary is the new one, so it is the one path that can.
                install_self_to_bin(&cfg.state_dir);
                return InstallOutcome {
                    status: out.status,
                    message: out.message,
                    to: out.to,
                    installed_at: cfg.install_root.clone(),
                };
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
    let toolchain_state = cfg.provision_toolchain.then_some(state.as_path());
    if let Err(e) = build_with_toolchain(&staging, toolchain_state, &mut *cfg.builder, progress) {
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

    // Everything past this point is best-effort: the checkout is built and
    // in place, and a missing shortcut is not a reason to undo that. Each step
    // says what happened, because a step that fails in silence is what made
    // the previous release impossible to diagnose.
    if cfg.provision_toolchain {
        crate::handoff::record_gpu_choice(
            &cfg.install_root,
            &cfg.state_dir,
            cfg.use_gpu,
            progress,
        );
        if let Err(e) =
            crate::handoff::install_essentials(&cfg.install_root, &cfg.state_dir, progress)
        {
            progress(&format!(
                "warning: some components did not install ({e}); run `marvi setup` to finish"
            ));
        }
        if let Err(e) =
            crate::handoff::install_cli_shim(&cfg.install_root, &cfg.state_dir, progress)
        {
            progress(&format!("warning: the marvi command was not installed ({e})"));
        }
        if let Err(e) = crate::handoff::create_shortcuts(&cfg.install_root, progress) {
            progress(&format!("warning: no shortcut was created ({e})"));
        }
    }

    let result = UpdateResult::new("ok", "Installed successfully.")
        .with_range("", to.as_deref().unwrap_or(""));
    let _ = crate::result::write_result(&cfg.state_dir, &result);

    // The STT engine ships as a release asset because no toolchain Marvi
    // provisions can build Rust. Without it a voice turn reaches the
    // microphone and stops, with nothing to turn audio into words.
    if let Some(tag) = to.as_deref() {
        if let Err(error) = crate::selfupdate::fetch_voice_runtime(&cfg.install_root, tag, progress)
        {
            progress(&format!("warning: could not fetch the voice runtime: {error}"));
        }
    }

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
    clear_build_output(root, progress);
    builder.prepare(root, progress)?;
    if !smoke_ok(root) {
        return Err("build produced no runnable runtime (smoke test failed)".to_string());
    }
    Ok(())
}

/// Remove the previous packaged build before rebuilding it.
///
/// electron-builder does this itself and reported
/// `EBUSY: resource busy or locked, rmdir dist\win-unpacked` when it could
/// not — which is what an update did, because the app being replaced runs from
/// inside that directory and Windows holds the file until every handle closes.
/// Killing the processes is the first half; the handles can outlive them by a
/// moment, so this retries rather than failing on the first refusal.
///
/// Best-effort: if it cannot be cleared, the build is still attempted and
/// electron-builder's own error is the honest one to report.
fn clear_build_output(root: &Path, progress: &mut dyn FnMut(&str)) {
    let unpacked = root.join("apps").join("desktop").join("dist").join("win-unpacked");
    if !unpacked.exists() {
        return;
    }
    for attempt in 1..=BUILD_OUTPUT_ATTEMPTS {
        match std::fs::remove_dir_all(&unpacked) {
            Ok(()) => {
                progress("cleared the previous build");
                return;
            }
            Err(_) if attempt < BUILD_OUTPUT_ATTEMPTS => {
                progress(&format!(
                    "the previous build is still in use, waiting ({attempt}/{BUILD_OUTPUT_ATTEMPTS})"
                ));
                std::thread::sleep(std::time::Duration::from_secs(2));
            }
            Err(error) => {
                // Said out loud rather than swallowed: if the build now fails
                // with EBUSY, this line is the reason.
                progress(&format!("could not clear the previous build: {error}"));
            }
        }
    }
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

/// The install root, from the packaged executable inside it.
///
/// `<root>/apps/desktop/dist/win-unpacked/Marvi-OS.exe` -> `<root>`. Falls back
/// to the executable's own directory if the layout is not what we expect, which
/// is the old behaviour and no worse than it was.
pub(crate) fn install_root_of(exe: &Path) -> PathBuf {
    exe.ancestors()
        .nth(5)
        .filter(|root| root.join("apps").is_dir())
        .map(PathBuf::from)
        .unwrap_or_else(|| exe.parent().unwrap_or(Path::new(".")).to_path_buf())
}

pub(crate) fn launch(exe: &Path) {
    if !exe.exists() {
        return;
    }
    // Deliberately NOT `exe.parent()`. That is `dist/win-unpacked`, and a
    // process's current directory is an open handle on it -- which is what made
    // the next update fail with
    //   EBUSY: resource busy or locked, rmdir ...\dist\win-unpacked
    // even after Marvi itself had exited, because every child Marvi spawns
    // inherits the directory and any one of them outliving the parent by a
    // moment keeps it pinned. Retrying could not fix that; nothing was going to
    // let go. Running from the install root pins a directory no build touches.
    let working_dir = install_root_of(exe);
    let _ = no_window(&mut std::process::Command::new(exe))
        .current_dir(working_dir)
        .spawn();
}

/// Copy the running bootstrap into `state_dir/bin` so the installed app can
/// hand off updates to it later. Skips the copy when already running from the
/// destination (a no-op that would otherwise fail on Windows).
fn install_self_to_bin(state_dir: &Path) {
    let Ok(exe) = std::env::current_exe() else {
        return;
    };
    copy_bootstrap(&exe, state_dir);
}

/// Put `exe` where the installed app looks for the updater.
///
/// Split from [`install_self_to_bin`] so it can be tested without being the
/// running process -- which is also the case it has to get right: the copy is
/// skipped when source and destination are the same file, because during an
/// in-app update the running binary *is* the destination and Windows will not
/// let a running executable be overwritten.
///
/// That skip is why an in-app update cannot deliver a new updater: the only
/// binary it has is the old one it is already running. Repair can, because
/// there the running binary is the freshly downloaded one.
pub(crate) fn copy_bootstrap(exe: &Path, state_dir: &Path) -> bool {
    let dir = state_dir.join("bin");
    if std::fs::create_dir_all(&dir).is_err() {
        return false;
    }
    let dest = dir.join("marvi-bootstrap.exe");
    // Compared canonically: the same file reached by two different paths is
    // still the same file, and copying it onto itself truncates it.
    let same = std::fs::canonicalize(exe)
        .ok()
        .zip(std::fs::canonicalize(&dest).ok())
        .map(|(a, b)| a == b)
        .unwrap_or(exe == dest);
    if same {
        return false;
    }
    std::fs::copy(exe, &dest).is_ok()
}

#[cfg(test)]
mod launch_tests {
    use super::install_root_of;
    use std::path::Path;

    /// The relaunched app must not run from inside the build output. Its current
    /// directory is an open handle, and the next update deletes that directory.
    #[test]
    fn the_relaunch_directory_is_outside_the_build_output() {
        let tmp = tempfile::TempDir::new().unwrap();
        let root = tmp.path();
        let unpacked = root.join("apps/desktop/dist/win-unpacked");
        std::fs::create_dir_all(&unpacked).unwrap();

        let working_dir = install_root_of(&unpacked.join("Marvi-OS.exe"));

        assert_eq!(working_dir, root);
        assert!(
            !working_dir.starts_with(&unpacked),
            "relaunching from {working_dir:?} pins the directory the next update deletes"
        );
    }

    /// An executable somewhere unexpected still gets a directory it can run in.
    #[test]
    fn an_unfamiliar_layout_falls_back_to_the_executable_directory() {
        let exe = Path::new("/somewhere/else/Marvi-OS.exe");
        assert_eq!(install_root_of(exe), Path::new("/somewhere/else"));
    }
}

#[cfg(test)]
mod bootstrap_copy_tests {
    use super::copy_bootstrap;

    /// Repairing with a newly downloaded installer must replace the old
    /// updater. It did not: the repair path returns before the copy that a
    /// fresh install does, so every fix to the updater itself never reached
    /// the machine that needed it -- and the updater is the one component a
    /// user cannot fix any other way.
    #[test]
    fn a_newer_bootstrap_replaces_the_installed_one() {
        let tmp = tempfile::TempDir::new().unwrap();
        let state = tmp.path().join("state");
        let installed = state.join("bin").join("marvi-bootstrap.exe");
        std::fs::create_dir_all(installed.parent().unwrap()).unwrap();
        std::fs::write(&installed, b"old version").unwrap();

        let fresh = tmp.path().join("downloaded.exe");
        std::fs::write(&fresh, b"new version").unwrap();

        assert!(copy_bootstrap(&fresh, &state));
        assert_eq!(std::fs::read(&installed).unwrap(), b"new version");
    }

    #[test]
    fn it_installs_where_none_was_before() {
        let tmp = tempfile::TempDir::new().unwrap();
        let state = tmp.path().join("state");
        let fresh = tmp.path().join("downloaded.exe");
        std::fs::write(&fresh, b"new version").unwrap();

        assert!(copy_bootstrap(&fresh, &state));
        assert!(state.join("bin").join("marvi-bootstrap.exe").is_file());
    }

    /// The in-app update case. Copying a file onto itself truncates it, which
    /// would leave the machine with no updater at all.
    #[test]
    fn it_refuses_to_copy_a_file_over_itself() {
        let tmp = tempfile::TempDir::new().unwrap();
        let state = tmp.path().join("state");
        let installed = state.join("bin").join("marvi-bootstrap.exe");
        std::fs::create_dir_all(installed.parent().unwrap()).unwrap();
        std::fs::write(&installed, b"running right now").unwrap();

        assert!(!copy_bootstrap(&installed, &state));
        assert_eq!(std::fs::read(&installed).unwrap(), b"running right now");
    }
}
