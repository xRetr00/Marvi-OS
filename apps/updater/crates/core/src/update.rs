//! In-place update with rollback.
//!
//! Safety ordering (priority order):
//!   1. Record the pre-update commit first; restore it on any failure.
//!   2. Fail closed: if the desktop never exits, abort without touching the
//!      checkout. Refuse a dirty tree rather than discard the user's edits.
//!   3. Snapshot the built runtime before rebuilding so a failed build cannot
//!      leave the user with a half-written app.
//!   4. Every path writes a result and (when the desktop actually exited)
//!      attempts a relaunch, so the user is never left with no app.

use std::path::{Path, PathBuf};
use std::time::{Duration, Instant};

use crate::builder::BuildRunner;
use crate::channels::Channel;
use crate::git::{self, SignatureStatus};
use crate::install::install_root_of;
use crate::marker;
use crate::result::UpdateResult;
use crate::tags;
use crate::util;
use crate::util::no_window;

const OUT_DIR: &str = "apps/desktop/out";
const DIST_DIR: &str = "apps/desktop/dist";
const WAIT_SECS: u64 = 60;

pub struct UpdateConfig {
    pub install_root: PathBuf,
    pub channel: Channel,
    pub state_dir: PathBuf,
    pub desktop_pid: Option<u32>,
    pub relaunch_exe: Option<PathBuf>,
    pub no_relaunch: bool,
    pub builder: Box<dyn BuildRunner>,
    /// False only in tests. Gates the toolchain download and the handoff — the
    /// handoff writes to the user's PATH and Desktop, which a test must never
    /// do, and the toolchain is ~100 MB per run.
    pub provision_toolchain: bool,
}

#[derive(Debug, Clone)]
pub struct UpdateOutcome {
    pub status: String,
    pub message: String,
    pub from: Option<String>,
    pub to: Option<String>,
    pub target_ref: Option<String>,
}

impl UpdateOutcome {
    fn new(status: &str, message: impl Into<String>) -> Self {
        UpdateOutcome {
            status: status.to_string(),
            message: message.into(),
            from: None,
            to: None,
            target_ref: None,
        }
    }

    fn with_range(mut self, from: &str, to: &str) -> Self {
        self.from = Some(from.to_string());
        self.to = Some(to.to_string());
        self
    }

    fn with_ref(mut self, r: Option<String>) -> Self {
        self.target_ref = r;
        self
    }
}

/// Perform the update. Writes and clears the in-progress marker; leaves result
/// writing and relaunch to [`finish`].
pub fn run_update(cfg: &mut UpdateConfig, progress: &mut dyn FnMut(&str)) -> UpdateOutcome {
    let _ = marker::write_marker(&cfg.state_dir);
    let root = cfg.install_root.clone();

    // One installer at a time. Two doing `git checkout` and `npm ci` in the
    // same directory corrupts the checkout with no clear cause.
    let _lock = match crate::singleton::acquire(&cfg.state_dir) {
        Ok(lock) => lock,
        Err(message) => {
            let out = UpdateOutcome::new("aborted", message);
            finish(cfg, &out, false);
            return out;
        }
    };

    // -- preflight: the desktop must actually exit (fails closed) ----------
    // If the app is still running the finish step must not relaunch, or the
    // user ends up with two instances.
    if let Some(pid) = cfg.desktop_pid {
        progress("waiting for Marvi OS to exit");
        if !wait_for_exit(pid, WAIT_SECS, progress) {
            let out = UpdateOutcome::new(
                "aborted",
                "Marvi OS did not exit in time; the installation was left untouched.",
            );
            finish(cfg, &out, false);
            return out;
        }
    }

    // The desktop exiting is not enough: its children outlive it, and one of
    // them still holding a file is the difference between an update that works
    // and one that fails inside git.
    let stopped = crate::singleton::clear_install_root(&root, progress);
    if !stopped.is_empty() {
        progress(&format!("stopped {}", stopped.join(", ")));
    }

    // -- preflight: usable, clean checkout ---------------------------------
    if !git::is_work_tree(&root) {
        let out = UpdateOutcome::new("failed", "No git checkout at the install path.");
        finish(cfg, &out, true);
        return out;
    }
    match git::is_dirty(&root) {
        Ok(true) => {
            let out = UpdateOutcome::new(
                "skipped",
                "Local changes present; update skipped to avoid discarding them.",
            );
            finish(cfg, &out, true);
            return out;
        }
        Ok(false) => {}
        Err(e) => {
            let out = UpdateOutcome::new("failed", format!("Could not inspect the checkout: {e}"));
            finish(cfg, &out, true);
            return out;
        }
    }

    // -- record the rollback point before touching anything ----------------
    let previous = match git::current_commit(&root) {
        Ok(c) => c,
        Err(e) => {
            let out =
                UpdateOutcome::new("failed", format!("Could not read the current commit: {e}"));
            finish(cfg, &out, true);
            return out;
        }
    };
    progress(&format!("current commit {}", short(&previous)));

    // -- resolve and fetch the target --------------------------------------
    let (target, target_ref) = match resolve_target(&root, cfg.channel, progress) {
        Ok(v) => v,
        Err((status, message)) => {
            let out = UpdateOutcome::new(status, message);
            finish(cfg, &out, true);
            return out;
        }
    };

    if target == previous {
        refresh_published_assets(cfg, &root, target_ref.as_deref(), progress);
        let out = UpdateOutcome::new("ok", "Already up to date.")
            .with_range(&previous, &target)
            .with_ref(target_ref);
        finish(cfg, &out, true);
        return out;
    }

    // -- snapshot built output so a failed build cannot break relaunch -----
    // Fails the update rather than proceeding without one. Proceeding is what
    // deleted an installation: the build output could not be moved aside, the
    // failure was swallowed, and the rollback later had nothing to restore.
    let backups = match snapshot_build_output(&root) {
        Ok(backups) => backups,
        Err(message) => {
            let out = UpdateOutcome::new(
                "aborted",
                format!("{message} The installation was left untouched."),
            );
            finish(cfg, &out, true);
            return out;
        }
    };

    // -- apply -------------------------------------------------------------
    progress(&format!("updating to {}", short(&target)));
    if let Err(e) = apply_target(&root, cfg.channel, &target_ref) {
        let _ = rollback(&root, &previous, &backups);
        let out = UpdateOutcome::new(
            "failed",
            format!("The update could not be applied cleanly. {e}"),
        )
        .with_range(&previous, &previous);
        finish(cfg, &out, true);
        return out;
    }

    // -- rebuild -----------------------------------------------------------
    progress("building");
    // Re-checked on every update, not just on install.
    let state = cfg.state_dir.clone();
    let toolchain_state = cfg.provision_toolchain.then_some(state.as_path());
    if let Err(e) =
        crate::install::build_with_toolchain(&root, toolchain_state, &mut *cfg.builder, progress)
    {
        let _ = rollback(&root, &previous, &backups);
        let out = UpdateOutcome::new("failed", format!("{e} The previous version was restored."))
            .with_range(&previous, &previous);
        finish(cfg, &out, true);
        return out;
    }

    progress("activating installation");
    discard_backups(&backups);

    // The updater updates itself last, from the newest published release.
    // This is deliberately independent of the app channel: nightly follows
    // origin/main, but there can never be a GitHub Release named origin/main.
    // This was the one component an update could not deliver: it is a compiled
    // binary
    // in state/bin, an update only rebuilds the JavaScript, and the running
    // process cannot overwrite the file it is executing. So every fix to the
    // updater sat in the checkout until someone downloaded an installer.
    //
    // Never fatal. An update that worked and could not refresh the updater is
    // still an update that worked, and the alternative -- failing the whole
    // thing over a download -- would make the machine harder to fix, not
    // easier.
    refresh_published_assets(cfg, &root, target_ref.as_deref(), progress);

    // Also on update, not only on install. An existing installation predates
    // the handoff entirely — no `marvi` command, no shortcut, no LiveKit
    // server — and updating is how those machines get them. Every step is
    // idempotent, so running it again on an already-good install costs a
    // couple of seconds and changes nothing.
    if cfg.provision_toolchain {
        if let Err(e) = crate::handoff::install_essentials(&root, &state, progress) {
            progress(&format!(
                "warning: some components did not install ({e}); run `marvi setup` to finish"
            ));
        }
        if let Err(e) = crate::handoff::install_cli_shim(&root, &state, progress) {
            progress(&format!(
                "warning: the marvi command was not installed ({e})"
            ));
        }
        if let Err(e) = crate::handoff::create_shortcuts(&root, progress) {
            progress(&format!("warning: no shortcut was created ({e})"));
        }
    }

    let out = UpdateOutcome::new("ok", "Updated successfully.")
        .with_range(&previous, &target)
        .with_ref(target_ref);
    finish(cfg, &out, true);
    out
}

/// Refresh native release assets without confusing the app's moving nightly ref
/// with a GitHub Release tag. This also runs on the already-current path: the
/// JavaScript checkout and the separately installed bootstrap can be at
/// different versions.
fn refresh_published_assets(
    cfg: &UpdateConfig,
    root: &Path,
    app_target_ref: Option<&str>,
    progress: &mut dyn FnMut(&str),
) {
    let tag = match published_release_tag(root, cfg.channel, app_target_ref) {
        Ok(Some(tag)) => tag,
        Ok(None) => return,
        Err(error) => {
            progress(&format!(
                "warning: could not resolve the updater release: {error}"
            ));
            return;
        }
    };

    progress(&format!("checking updater release {tag}"));

    // The STT engine, which no local toolchain can build. Not fatal: an
    // update that worked and could not fetch it is still an update that
    // worked, and voice is no worse off than before.
    if let Err(error) = crate::selfupdate::fetch_voice_runtime(root, &tag, progress) {
        progress(&format!(
            "warning: could not fetch the voice runtime: {error}"
        ));
    }

    match crate::selfupdate::refresh(&cfg.state_dir, root, &tag, progress) {
        Ok(true) => progress("the updater will be the new one from the next launch"),
        Ok(false) => {}
        Err(error) => progress(&format!("warning: could not refresh the updater: {error}")),
    }
}

/// Select the release carrying native assets. Release-channel app updates
/// already resolved a concrete tag. Dev updates instead resolve the newest
/// published tag independently; `origin/main` is a git ref, not a release.
fn published_release_tag(
    root: &Path,
    channel: Channel,
    app_target_ref: Option<&str>,
) -> Result<Option<String>, String> {
    match channel {
        Channel::Release => Ok(app_target_ref
            .filter(|name| tags::parse_release_tag(name).is_some())
            .map(str::to_owned)),
        Channel::Nightly => {
            let remote_tags = git::ls_remote_tags(root)
                .map_err(|error| format!("could not list release tags: {error}"))?;
            Ok(tags::latest(remote_tags).map(|(tag, _)| tag))
        }
    }
}

/// Write the result, clear the marker, and (when the desktop exited) relaunch.
fn finish(cfg: &UpdateConfig, out: &UpdateOutcome, do_relaunch: bool) {
    let result = UpdateResult::new(&out.status, &out.message)
        .with_range(
            out.from.as_deref().unwrap_or(""),
            out.to.as_deref().unwrap_or(""),
        )
        .with_channel(cfg.channel)
        .with_branch(out.target_ref.as_deref());
    let _ = crate::result::write_result(&cfg.state_dir, &result);
    marker::clear_marker(&cfg.state_dir);
    if do_relaunch && !cfg.no_relaunch {
        launch_exe(cfg.relaunch_exe.as_deref());
    }
}

/// Resolve the target commit and a human ref for the channel.
fn resolve_target(
    root: &Path,
    channel: Channel,
    progress: &mut dyn FnMut(&str),
) -> Result<(String, Option<String>), (&'static str, String)> {
    match channel {
        Channel::Nightly => {
            if let Err(e) = git::fetch_origin(root) {
                return Err(("failed", format!("Could not reach the update server: {e}")));
            }
            let target = git::resolve_commit(root, "origin/main")
                .map_err(|e| ("failed", format!("Branch origin/main not found: {e}")))?;
            Ok((target, Some("origin/main".to_string())))
        }
        Channel::Release => {
            let tags = git::ls_remote_tags(root)
                .map_err(|e| ("failed", format!("Could not reach the update server: {e}")))?;
            let (tag, _) = tags::latest(tags)
                .ok_or(("failed", "No release tags found on origin.".to_string()))?;
            if let Err(e) = git::fetch_tags(root) {
                return Err(("failed", format!("Could not fetch release tags: {e}")));
            }
            match git::verify_tag(root, &tag) {
                Ok(SignatureStatus::Invalid(detail)) => {
                    return Err((
                        "failed",
                        format!("Release tag {tag} has an invalid signature: {detail}"),
                    ));
                }
                Ok(SignatureStatus::Unsigned) => {
                    progress(&format!("warning: release tag {tag} is unsigned"));
                }
                Ok(SignatureStatus::Unverifiable(detail)) => {
                    // A warning, not a refusal. Blocking here means an
                    // installation that cannot verify can never update -- and
                    // the thing it is missing arrives *in* the update.
                    progress(&format!(
                        "warning: could not verify the signature on {tag}: {detail}"
                    ));
                }
                _ => {}
            }
            let target = git::resolve_commit(root, &tag).map_err(|e| {
                (
                    "failed",
                    format!("Could not resolve release tag {tag}: {e}"),
                )
            })?;
            Ok((target, Some(tag)))
        }
    }
}

fn apply_target(root: &Path, channel: Channel, target_ref: &Option<String>) -> Result<(), String> {
    match channel {
        Channel::Nightly => {
            ensure_on_main(root)?;
            git::merge_ff_only(root, "origin/main").map_err(|e| e.to_string())
        }
        Channel::Release => {
            let tag = target_ref.as_deref().ok_or("missing release tag")?;
            git::checkout(root, tag).map_err(|e| e.to_string())
        }
    }
}

fn ensure_on_main(root: &Path) -> Result<(), String> {
    let has_main = git::run_status(root, &["rev-parse", "--verify", "--quiet", "main"])
        .map(|s| s.success())
        .map_err(|e| e.to_string())?;
    if has_main {
        git::checkout(root, "main").map_err(|e| e.to_string())?;
    } else {
        git::run(root, &["checkout", "-b", "main", "--track", "origin/main"])
            .map_err(|e| e.to_string())?;
    }
    Ok(())
}

/// Best-effort wait for the desktop process to exit.
fn wait_for_exit(pid: u32, timeout_secs: u64, progress: &mut dyn FnMut(&str)) -> bool {
    let deadline = Instant::now() + Duration::from_secs(timeout_secs);
    while Instant::now() < deadline {
        if !util::process_alive(pid) {
            return true;
        }
        progress("waiting for Marvi OS to exit");
        std::thread::sleep(Duration::from_secs(1));
    }
    !util::process_alive(pid)
}

struct Backup {
    original: PathBuf,
    backup: PathBuf,
}

/// Move the built runtime aside so a failed build can be undone.
///
/// Errors rather than skipping. It used to `.ok()` a failed rename, which is
/// how an update destroyed an installation: the desktop was still holding
/// `dist`, so the rename failed, so no backup was recorded -- silently -- and
/// the update carried on believing it could roll back. electron-builder then
/// emptied `dist` itself, failed partway with EBUSY, and the rollback had
/// nothing to put back. The app was gone and no retry brought it back.
///
/// A snapshot that did not happen is worse than no snapshot, because
/// everything after it assumes the undo will work.
fn snapshot_build_output(root: &Path) -> Result<Vec<Backup>, String> {
    let mut backups = Vec::new();
    for rel in [OUT_DIR, DIST_DIR] {
        let original = root.join(rel);
        if !original.exists() {
            continue;
        }
        let backup = root.join(format!("{}.marvi-bak", rel.replace('/', "-")));
        // A leftover from an interrupted run would fail the rename for a
        // reason that has nothing to do with the app still running.
        let _ = std::fs::remove_dir_all(&backup);
        match std::fs::rename(&original, &backup) {
            Ok(()) => backups.push(Backup { original, backup }),
            Err(error) => {
                // Put back whatever did move, so a refusal leaves the
                // installation exactly as it was found.
                restore_build_output(&backups);
                return Err(format!(
                    "{} could not be backed up ({error}). Marvi may still be running.",
                    original.display()
                ));
            }
        }
    }
    Ok(backups)
}

fn discard_backups(backups: &[Backup]) {
    for b in backups {
        let _ = std::fs::remove_dir_all(&b.backup);
    }
}

fn restore_build_output(backups: &[Backup]) {
    for b in backups {
        let _ = std::fs::remove_dir_all(&b.original);
        let _ = std::fs::rename(&b.backup, &b.original);
    }
}

/// Restore the previous commit and built runtime, then verify the restore.
fn rollback(root: &Path, previous: &str, backups: &[Backup]) -> Result<(), String> {
    git::reset_hard(root, previous).map_err(|e| e.to_string())?;
    let now = git::current_commit(root).map_err(|e| e.to_string())?;
    if now != previous {
        return Err(format!(
            "rollback verification failed: HEAD is {now}, expected {previous}"
        ));
    }
    restore_build_output(backups);
    Ok(())
}

fn launch_exe(exe: Option<&Path>) {
    let Some(exe) = exe else { return };
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

fn short(sha: &str) -> &str {
    sha.get(..8).unwrap_or(sha)
}

#[cfg(test)]
mod snapshot_tests {
    use super::{DIST_DIR, OUT_DIR, snapshot_build_output};

    /// The failure that deleted an installation.
    ///
    /// The desktop was still holding `dist`, so the rename failed. That was
    /// `.ok()`d, so no backup was recorded -- silently -- and the update
    /// carried on believing it could roll back. electron-builder then emptied
    /// `dist` itself, failed partway with EBUSY, and the rollback had nothing
    /// to put back.
    #[test]
    fn a_snapshot_that_cannot_be_taken_is_an_error_not_a_shrug() {
        let tmp = tempfile::TempDir::new().unwrap();
        let root = tmp.path();
        std::fs::create_dir_all(root.join(OUT_DIR)).unwrap();
        std::fs::create_dir_all(root.join(DIST_DIR)).unwrap();

        // The real condition: a file inside `dist` held open, which is what a
        // running Marvi does to its own executable. Windows refuses to rename
        // a directory out from under an open handle.
        let held = root
            .join(DIST_DIR)
            .join("win-unpacked")
            .join("Marvi-OS.exe");
        std::fs::create_dir_all(held.parent().unwrap()).unwrap();
        std::fs::write(&held, b"pretend executable").unwrap();
        let handle = std::fs::File::open(&held).unwrap();

        let result = snapshot_build_output(root);
        drop(handle);

        assert!(result.is_err(), "a failed snapshot must be reported");
        // And the one that did move is put back, so a refusal leaves the
        // installation exactly as it was found.
        assert!(root.join(OUT_DIR).is_dir(), "out was not restored");
        assert!(root.join(DIST_DIR).is_dir(), "dist should be untouched");
    }

    #[test]
    fn a_clean_snapshot_moves_both_directories_aside() {
        let tmp = tempfile::TempDir::new().unwrap();
        let root = tmp.path();
        std::fs::create_dir_all(root.join(OUT_DIR)).unwrap();
        std::fs::create_dir_all(root.join(DIST_DIR)).unwrap();

        let backups = snapshot_build_output(root).expect("nothing is holding these");

        assert_eq!(backups.len(), 2);
        assert!(!root.join(OUT_DIR).exists());
        assert!(!root.join(DIST_DIR).exists());
    }

    #[test]
    fn nothing_built_yet_is_not_a_failure() {
        let tmp = tempfile::TempDir::new().unwrap();

        assert_eq!(snapshot_build_output(tmp.path()).unwrap().len(), 0);
    }
}
