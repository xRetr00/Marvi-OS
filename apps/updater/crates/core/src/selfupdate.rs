//! Replacing the updater with a newer updater.
//!
//! The bootstrap is the one component that cannot be fixed by updating,
//! because it is what performs the update. Every fix to it — the EBUSY on
//! `win-unpacked`, the signature check that rejected a good tag, the console
//! windows — reached the checkout and then sat there, because the binary that
//! runs is a compiled copy in `state/bin` and an update only rebuilds the
//! JavaScript.
//!
//! Repair could fix it, since there the running binary is a freshly downloaded
//! one, but that means noticing something is wrong and going to fetch an
//! installer — which is the situation the updater exists to avoid.
//!
//! **How it replaces something it is running from.** Windows will not let a
//! running executable be overwritten, but it will let one be *renamed*: the
//! handle follows the file, not the path. So the current binary is moved aside
//! and the new one takes its name. The running process keeps executing from
//! the renamed file, finishes the update it was in the middle of, and the next
//! launch gets the new one. The leftovers are swept on the following run,
//! by which point nothing holds them.
//!
//! **What is trusted.** The binary is downloaded from the release for the tag
//! being installed and checked against `SHA256SUMS.txt` from the same release.
//! A hash that does not match means nothing is replaced — an updater that
//! installs an unverified updater over itself is a worse failure than an
//! out-of-date one.

use std::path::{Path, PathBuf};
use std::time::Duration;

use crate::util;

/// Long enough for a few megabytes on a slow connection, short enough that a
/// hung download does not hold the update open.
const DOWNLOAD_TIMEOUT: Duration = Duration::from_secs(180);

const ASSET: &str = "marvi-bootstrap.exe";
const CHECKSUMS: &str = "SHA256SUMS.txt";

/// Where the installed updater lives, and what a superseded one is called.
pub fn installed_path(state_dir: &Path) -> PathBuf {
    state_dir.join("bin").join(ASSET)
}

fn retired_prefix() -> &'static str {
    "marvi-bootstrap.old-"
}

/// Delete superseded binaries left by earlier self-updates.
///
/// Best effort and deliberately quiet. One that is still held simply stays for
/// the next run; a few hundred kilobytes is not worth reporting as a problem.
pub fn sweep(state_dir: &Path) {
    let Ok(entries) = std::fs::read_dir(state_dir.join("bin")) else {
        return;
    };
    for entry in entries.flatten() {
        let name = entry.file_name();
        let name = name.to_string_lossy();
        if name.starts_with(retired_prefix()) {
            let _ = std::fs::remove_file(entry.path());
        }
    }
}

/// The release download URL for one asset of one tag.
fn asset_url(repo: &str, tag: &str, asset: &str) -> String {
    format!("https://github.com/{repo}/releases/download/{tag}/{asset}")
}

/// `owner/name` from a remote URL, in either form git uses.
pub fn repo_slug(remote: &str) -> Option<String> {
    let trimmed = remote.trim().trim_end_matches('/').trim_end_matches(".git");
    let tail = if let Some(rest) = trimmed.strip_prefix("git@github.com:") {
        rest
    } else {
        trimmed.split("github.com/").nth(1)?
    };
    let mut parts = tail.split('/');
    let owner = parts.next().filter(|s| !s.is_empty())?;
    let name = parts.next().filter(|s| !s.is_empty())?;
    Some(format!("{owner}/{name}"))
}

/// The SHA-256 of a file, uppercase hex, or None if it cannot be computed.
#[cfg(windows)]
fn sha256(path: &Path, cwd: &Path) -> Option<String> {
    let mut captured = String::new();
    let script = format!(
        "(Get-FileHash -Algorithm SHA256 -LiteralPath '{}').Hash",
        path.display()
    );
    util::run_powershell(&script, cwd, DOWNLOAD_TIMEOUT, &mut |line| {
        let line = line.trim();
        if line.len() == 64 && line.chars().all(|c| c.is_ascii_hexdigit()) {
            captured = line.to_ascii_uppercase();
        }
    })
    .ok()?;
    (!captured.is_empty()).then_some(captured)
}

#[cfg(not(windows))]
fn sha256(path: &Path, cwd: &Path) -> Option<String> {
    let mut captured = String::new();
    let script = format!("shasum -a 256 '{}' | cut -d' ' -f1", path.display());
    util::run_shell_reporting(&script, cwd, DOWNLOAD_TIMEOUT, &mut |line| {
        let line = line.trim();
        if line.len() == 64 && line.chars().all(|c| c.is_ascii_hexdigit()) {
            captured = line.to_ascii_uppercase();
        }
    })
    .ok()?;
    (!captured.is_empty()).then_some(captured)
}

/// Find `ASSET`'s expected hash in a SHA256SUMS file.
///
/// The format is `<hash>␣␣<name>`, and the name may carry a path prefix from
/// wherever it was generated, so it is matched on the file name alone.
pub fn expected_hash(sums: &str, asset: &str) -> Option<String> {
    for line in sums.lines() {
        let mut parts = line.split_whitespace();
        let hash = parts.next()?;
        let Some(name) = parts.next() else { continue };
        let name = name.trim_start_matches('*');
        if Path::new(name).file_name().map(|n| n == asset).unwrap_or(false) {
            return Some(hash.to_ascii_uppercase());
        }
    }
    None
}

#[cfg(windows)]
fn download(url: &str, to: &Path, cwd: &Path, progress: &mut dyn FnMut(&str)) -> Result<(), String> {
    let script = format!(
        "$ProgressPreference='SilentlyContinue'; \
         Invoke-WebRequest -Uri '{url}' -OutFile '{}' -UseBasicParsing",
        to.display()
    );
    util::run_powershell(&script, cwd, DOWNLOAD_TIMEOUT, progress)
}

#[cfg(not(windows))]
fn download(url: &str, to: &Path, cwd: &Path, progress: &mut dyn FnMut(&str)) -> Result<(), String> {
    let script = format!("curl -fsSL '{url}' -o '{}'", to.display());
    util::run_shell_reporting(&script, cwd, DOWNLOAD_TIMEOUT, progress)
}

fn read_to_string(path: &Path) -> Option<String> {
    std::fs::read_to_string(path).ok()
}

/// Put `fresh` where the installed updater lives, moving the old one aside.
///
/// Separate from the download so the rename dance can be tested without a
/// network: it is the part that has to be right, because getting it wrong
/// leaves a machine with no updater at all.
pub fn swap_in(fresh: &Path, state_dir: &Path) -> Result<(), String> {
    let target = installed_path(state_dir);
    if let Some(parent) = target.parent() {
        std::fs::create_dir_all(parent)
            .map_err(|e| format!("could not create {}: {e}", parent.display()))?;
    }

    if target.exists() {
        let retired = target.with_file_name(format!(
            "{}{}.exe",
            retired_prefix(),
            util::epoch_ms()
        ));
        // Renaming works on a running executable; overwriting does not.
        std::fs::rename(&target, &retired)
            .map_err(|e| format!("could not move the current updater aside: {e}"))?;

        if let Err(error) = std::fs::rename(fresh, &target) {
            // Put it back rather than leaving the machine with nothing at the
            // path the app launches.
            let _ = std::fs::rename(&retired, &target);
            return Err(format!("could not install the new updater: {error}"));
        }
        return Ok(());
    }

    std::fs::rename(fresh, &target).map_err(|e| format!("could not install the updater: {e}"))
}

/// The speech-to-text engine, fetched from the release rather than built.
///
/// It is Rust, and the toolchain Marvi provisions is uv and Node -- there is no
/// cargo on a user's machine, so nothing installed there could ever build it.
/// Nothing did: an installed Marvi had no STT binary at all, and a voice turn
/// reached the microphone and then stopped, because the thing that turns audio
/// into words was never present. The wake word fired, the session listened,
/// and no transcript was ever produced.
///
/// Verified against the same SHA256SUMS.txt as the updater. A voice runtime is
/// a native binary that listens to a microphone; downloading one unverified is
/// not a thing to do.
pub fn fetch_voice_runtime(
    install_root: &Path,
    tag: &str,
    progress: &mut dyn FnMut(&str),
) -> Result<bool, String> {
    const ASSET: &str = "marvi-voice-runtime.exe";

    let remote = crate::git::remote_url(install_root).map_err(|e| e.to_string())?;
    let Some(repo) = repo_slug(&remote) else {
        return Ok(false);
    };

    let target = install_root
        .join("services")
        .join("voice-runtime")
        .join("target")
        .join("release")
        .join(ASSET);
    let staging = target.with_extension("exe.new");
    let sums = target.with_file_name("SHA256SUMS.txt");
    std::fs::create_dir_all(target.parent().unwrap_or(install_root))
        .map_err(|e| format!("could not prepare the voice runtime directory: {e}"))?;

    progress("fetching the speech-to-text engine");
    download(&asset_url(&repo, tag, CHECKSUMS), &sums, install_root, progress)?;
    let expected = read_to_string(&sums).as_deref().and_then(|s| expected_hash(s, ASSET));
    let _ = std::fs::remove_file(&sums);
    let Some(expected) = expected else {
        // A release from before this asset existed. Not an error: the rest of
        // the update is still good, and voice was no worse off than it was.
        return Ok(false);
    };

    download(&asset_url(&repo, tag, ASSET), &staging, install_root, progress)?;
    let actual = sha256(&staging, install_root);
    if actual.as_deref() != Some(expected.as_str()) {
        let _ = std::fs::remove_file(&staging);
        return Err(format!(
            "the downloaded voice runtime did not match its published checksum ({} vs {expected})",
            actual.as_deref().unwrap_or("unreadable")
        ));
    }

    // Replaced by rename, like the updater: it may be running, and Windows
    // will move a running executable even though it will not overwrite one.
    if target.exists() {
        let retired = target.with_file_name(format!("marvi-voice-runtime.old-{}.exe", util::epoch_ms()));
        let _ = std::fs::rename(&target, &retired);
        let _ = std::fs::remove_file(&retired);
    }
    std::fs::rename(&staging, &target)
        .map_err(|e| format!("could not install the voice runtime: {e}"))?;
    progress("the speech-to-text engine is installed");
    Ok(true)
}

/// Download the updater published with `tag` and put it in place.
///
/// Returns Ok(false) when there is nothing to do or the release does not carry
/// one. Never fatal to the update that called it: an update that succeeded and
/// could not refresh the updater is still a successful update.
pub fn refresh(
    state_dir: &Path,
    install_root: &Path,
    tag: &str,
    progress: &mut dyn FnMut(&str),
) -> Result<bool, String> {
    sweep(state_dir);

    let remote = crate::git::remote_url(install_root).map_err(|e| e.to_string())?;
    let Some(repo) = repo_slug(&remote) else {
        return Ok(false);
    };

    let staging = state_dir.join("bin").join("marvi-bootstrap.new.exe");
    let sums = state_dir.join("bin").join("SHA256SUMS.txt");
    let _ = std::fs::create_dir_all(state_dir.join("bin"));

    progress("checking for a newer updater");
    download(&asset_url(&repo, tag, CHECKSUMS), &sums, install_root, progress)?;
    let Some(expected) = read_to_string(&sums).as_deref().and_then(|s| expected_hash(s, ASSET))
    else {
        let _ = std::fs::remove_file(&sums);
        return Ok(false);
    };

    download(&asset_url(&repo, tag, ASSET), &staging, install_root, progress)?;

    let actual = sha256(&staging, install_root);
    let _ = std::fs::remove_file(&sums);
    if actual.as_deref() != Some(expected.as_str()) {
        // Nothing is replaced. Installing an unverified updater over the one
        // that does the verifying is a worse failure than being out of date.
        let _ = std::fs::remove_file(&staging);
        return Err(format!(
            "the downloaded updater did not match its published checksum ({} vs {expected})",
            actual.as_deref().unwrap_or("unreadable")
        ));
    }

    swap_in(&staging, state_dir)?;
    progress("the updater was replaced with the one from this release");
    Ok(true)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_remote_url_becomes_owner_and_name() {
        for remote in [
            "https://github.com/xRetr00/Marvi-OS.git",
            "https://github.com/xRetr00/Marvi-OS",
            "git@github.com:xRetr00/Marvi-OS.git",
            "https://github.com/xRetr00/Marvi-OS/",
        ] {
            assert_eq!(repo_slug(remote).as_deref(), Some("xRetr00/Marvi-OS"), "{remote}");
        }
    }

    #[test]
    fn a_remote_somewhere_else_is_not_guessed_at() {
        // Self-update is a GitHub releases feature. A checkout from anywhere
        // else simply does not get one, rather than getting a wrong URL.
        assert_eq!(repo_slug("https://gitlab.com/someone/thing.git"), None);
        assert_eq!(repo_slug("/a/local/path"), None);
    }

    #[test]
    fn the_expected_hash_is_found_by_file_name() {
        let sums = "\
abc123  release/marvi-bootstrap.exe
def456  something-else.txt
";
        assert_eq!(expected_hash(sums, ASSET).as_deref(), Some("ABC123"));
    }

    #[test]
    fn a_checksum_file_without_our_asset_yields_nothing() {
        assert_eq!(expected_hash("def456  other.txt\n", ASSET), None);
    }

    #[test]
    fn swapping_moves_the_old_one_aside_and_installs_the_new() {
        let tmp = tempfile::TempDir::new().unwrap();
        let state = tmp.path().join("state");
        let target = installed_path(&state);
        std::fs::create_dir_all(target.parent().unwrap()).unwrap();
        std::fs::write(&target, b"the running updater").unwrap();

        let fresh = tmp.path().join("fresh.exe");
        std::fs::write(&fresh, b"the new updater").unwrap();

        swap_in(&fresh, &state).unwrap();

        assert_eq!(std::fs::read(&target).unwrap(), b"the new updater");
        // The old one still exists: the process running from it has to keep
        // running, so it is retired rather than deleted.
        let retired: Vec<_> = std::fs::read_dir(state.join("bin"))
            .unwrap()
            .flatten()
            .filter(|e| e.file_name().to_string_lossy().starts_with(retired_prefix()))
            .collect();
        assert_eq!(retired.len(), 1);
        assert_eq!(std::fs::read(retired[0].path()).unwrap(), b"the running updater");
    }

    #[test]
    fn swapping_into_an_empty_directory_just_installs() {
        let tmp = tempfile::TempDir::new().unwrap();
        let state = tmp.path().join("state");
        let fresh = tmp.path().join("fresh.exe");
        std::fs::write(&fresh, b"the new updater").unwrap();

        swap_in(&fresh, &state).unwrap();

        assert_eq!(std::fs::read(installed_path(&state)).unwrap(), b"the new updater");
    }

    #[test]
    fn the_sweep_clears_retired_binaries_but_not_the_live_one() {
        let tmp = tempfile::TempDir::new().unwrap();
        let state = tmp.path().join("state");
        let bin = state.join("bin");
        std::fs::create_dir_all(&bin).unwrap();
        std::fs::write(installed_path(&state), b"live").unwrap();
        std::fs::write(bin.join(format!("{}123.exe", retired_prefix())), b"old").unwrap();

        sweep(&state);

        assert!(installed_path(&state).is_file());
        assert!(!bin.join(format!("{}123.exe", retired_prefix())).exists());
    }
}
