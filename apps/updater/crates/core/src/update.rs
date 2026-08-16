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
use crate::install::build_and_smoke;
use crate::marker;
use crate::result::UpdateResult;
use crate::tags;
use crate::util;

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
        let out = UpdateOutcome::new("ok", "Already up to date.")
            .with_range(&previous, &target)
            .with_ref(target_ref);
        finish(cfg, &out, true);
        return out;
    }

    // -- snapshot built output so a failed build cannot break relaunch -----
    let backups = snapshot_build_output(&root);

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
    if let Err(e) = build_and_smoke(&root, &mut *cfg.builder, progress) {
        let _ = rollback(&root, &previous, &backups);
        let out = UpdateOutcome::new("failed", format!("{e} The previous version was restored."))
            .with_range(&previous, &previous);
        finish(cfg, &out, true);
        return out;
    }

    discard_backups(&backups);
    let out = UpdateOutcome::new("ok", "Updated successfully.")
        .with_range(&previous, &target)
        .with_ref(target_ref);
    finish(cfg, &out, true);
    out
}

/// Write the result, clear the marker, and (when the desktop exited) relaunch.
fn finish(cfg: &UpdateConfig, out: &UpdateOutcome, do_relaunch: bool) {
    let result = UpdateResult::new(&out.status, &out.message)
        .with_range(out.from.as_deref().unwrap_or(""), out.to.as_deref().unwrap_or(""))
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
        Channel::Dev => {
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
                _ => {}
            }
            let target = git::resolve_commit(root, &tag)
                .map_err(|e| ("failed", format!("Could not resolve release tag {tag}: {e}")))?;
            Ok((target, Some(tag)))
        }
    }
}

fn apply_target(root: &Path, channel: Channel, target_ref: &Option<String>) -> Result<(), String> {
    match channel {
        Channel::Dev => {
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

fn snapshot_build_output(root: &Path) -> Vec<Backup> {
    [OUT_DIR, DIST_DIR]
        .iter()
        .filter_map(|rel| {
            let original = root.join(rel);
            if !original.exists() {
                return None;
            }
            let backup = root.join(format!("{}.marvi-bak", rel.replace('/', "-")));
            std::fs::rename(&original, &backup)
                .ok()
                .map(|_| Backup { original, backup })
        })
        .collect()
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
    let working_dir = exe.parent().unwrap_or(Path::new("."));
    let _ = std::process::Command::new(exe).current_dir(working_dir).spawn();
}

fn short(sha: &str) -> &str {
    sha.get(..8).unwrap_or(sha)
}
