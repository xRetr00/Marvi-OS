//! What the installer leaves behind once the build succeeds.
//!
//! A checkout that builds is not an installation. v0.1.3 finished with no
//! LiveKit server, no `marvi` command, and no way to start the app except by
//! finding the folder — every one of which reads as "Marvi is broken" rather
//! than "the installer stopped early".
//!
//! Four things, in order of how badly their absence hurts:
//!
//! 1. **Essential components.** The Python environments and the LiveKit server.
//!    Marvi's own catalog decides which ones; this only runs `marvi setup`.
//! 2. **The GPU answer.** Recorded before the Python environments are built,
//!    because it picks the PyTorch index and getting it wrong means a
//!    multi-gigabyte reinstall.
//! 3. **`marvi` on PATH.** The CLI is what works when the app does not, so it
//!    has to be reachable from a shell the user opens themselves.
//! 4. **A shortcut.** Nobody should have to know where the checkout is.
//!
//! Every step is best-effort: a missing shortcut is not a reason to undo a
//! working install. Each one reports what happened, because silence is what
//! made the last release so hard to diagnose.

use std::path::{Path, PathBuf};
use std::time::Duration;

use crate::toolchain::{Tool, managed_tool_path};
use crate::util::run_reporting;

/// Strip Windows' extended-length `\\?\` prefix.
///
/// `Path::canonicalize` produces it, and most of Windows accepts it — but the
/// COM shell object behind a `.lnk` does not, and rejects the whole call with
/// an ArgumentException. Anywhere a path is handed to something outside this
/// process, it goes through here first.
#[cfg(windows)]
fn plain(path: &Path) -> String {
    let text = path.display().to_string();
    text.strip_prefix(r"\\?\UNC\")
        .map(|rest| format!(r"\\{rest}"))
        .or_else(|| text.strip_prefix(r"\\?\").map(str::to_string))
        .unwrap_or(text)
}

/// Model downloads and `uv sync` over a slow link are genuinely slow.
const SETUP_TIMEOUT: Duration = Duration::from_secs(3_600);

/// Where the launcher and the `marvi` shim live. Added to the user's PATH.
pub fn bin_dir(state_dir: &Path) -> PathBuf {
    state_dir.join("bin")
}

/// Record the GPU answer before anything reads it.
///
/// `use_gpu: None` means the user was not asked — an unattended install, or a
/// machine with no GPU — and Marvi's own detection decides.
pub fn record_gpu_choice(
    install_root: &Path,
    state_dir: &Path,
    use_gpu: Option<bool>,
    progress: &mut dyn FnMut(&str),
) {
    let Some(use_gpu) = use_gpu else { return };
    let choice = if use_gpu { "gpu" } else { "cpu" };
    progress(&format!("recording GPU preference: {choice}"));
    let _ = marvi(
        install_root,
        state_dir,
        &["gpu", choice],
        Duration::from_secs(120),
        progress,
    );
}

/// Install the components Marvi cannot start without.
pub fn install_essentials(
    install_root: &Path,
    state_dir: &Path,
    progress: &mut dyn FnMut(&str),
) -> Result<(), String> {
    progress("installing the LiveKit server and Python environments");
    marvi(
        install_root,
        state_dir,
        &["setup", "--essential", "--yes"],
        SETUP_TIMEOUT,
        progress,
    )
}

/// Run Marvi's own CLI out of the checkout, using the toolchain just installed.
///
/// Not `marvi` from PATH: the point of provisioning `uv` was to stop depending
/// on whatever PATH this process happens to have.
fn marvi(
    install_root: &Path,
    state_dir: &Path,
    args: &[&str],
    timeout: Duration,
    progress: &mut dyn FnMut(&str),
) -> Result<(), String> {
    let uv = managed_tool_path(state_dir, Tool::Uv);
    if !uv.exists() {
        return Err(format!("uv is not installed at {}", uv.display()));
    }
    let uv = uv.display().to_string();
    let mut argv: Vec<&str> = vec!["run", "--project", "services/gateway", "marvi"];
    argv.extend_from_slice(args);
    run_reporting(&uv, &argv, install_root, timeout, progress)
}

/// Put `marvi` on the user's PATH.
///
/// A `.cmd` shim rather than a copied executable: the CLI lives in the
/// checkout and changes with every update, so the shim forwards to it and
/// never goes stale. `%*` passes the arguments through unchanged.
///
/// The shim is what fixed the reported collision — another tool's `marvi` was
/// earlier on PATH — because Marvi's entry is prepended, not appended.
#[cfg(windows)]
pub fn install_cli_shim(
    install_root: &Path,
    state_dir: &Path,
    progress: &mut dyn FnMut(&str),
) -> Result<(), String> {
    let bin = write_shim(install_root, state_dir, progress)?;
    prepend_user_path(&bin, progress)
}

/// Write the shim and return the directory holding it.
///
/// Separate from the PATH change so a test can check the shim's contents
/// without editing the machine it runs on — the first version of this did edit
/// it, and left three temporary directories on the author's PATH.
#[cfg(windows)]
fn write_shim(
    install_root: &Path,
    state_dir: &Path,
    progress: &mut dyn FnMut(&str),
) -> Result<PathBuf, String> {
    let bin = bin_dir(state_dir);
    std::fs::create_dir_all(&bin).map_err(|e| format!("could not create {bin:?}: {e}"))?;

    let uv = managed_tool_path(state_dir, Tool::Uv);
    let shim = bin.join("marvi.cmd");
    let body = format!(
        "@echo off\r\n\
         rem Generated by the Marvi installer. Forwards to the current checkout,\r\n\
         rem so an update never leaves a stale copy of the CLI behind.\r\n\
         \"{uv}\" run --project \"{root}\\services\\gateway\" marvi %*\r\n",
        uv = plain(&uv),
        root = plain(install_root)
    );
    std::fs::write(&shim, body).map_err(|e| format!("could not write {shim:?}: {e}"))?;
    progress(&format!("installed the marvi command to {}", shim.display()));
    Ok(bin)
}

/// Prepend a directory to the user's persistent `PATH`.
///
/// Read from the registry rather than from `%PATH%`: the process environment
/// is the *expanded* union of the machine and user values, and writing that
/// back would freeze the machine half into the user's own PATH forever.
#[cfg(windows)]
fn prepend_user_path(dir: &Path, progress: &mut dyn FnMut(&str)) -> Result<(), String> {
    let dir = plain(dir);
    // `GetEnvironmentVariable('Path','User')` returns the unexpanded user value
    // only. SetEnvironmentVariable broadcasts the change, so a shell opened
    // afterwards sees it without a sign-out.
    let script = format!(
        "$dir = '{dir}'; \
         $current = [Environment]::GetEnvironmentVariable('Path','User'); \
         $parts = @($current -split ';' | Where-Object {{ $_ -and $_ -ne $dir }}); \
         [Environment]::SetEnvironmentVariable('Path', (@($dir) + $parts) -join ';', 'User'); \
         Write-Output \"marvi is on PATH via $dir\""
    );
    crate::util::run_powershell(
        &script,
        Path::new("."),
        Duration::from_secs(60),
        progress,
    )
}

/// A Start-menu and Desktop shortcut for the installed app.
#[cfg(windows)]
pub fn create_shortcuts(
    install_root: &Path,
    progress: &mut dyn FnMut(&str),
) -> Result<(), String> {
    // The unpacked Electron build. `build:unpack` names the directory after the
    // product, so it is found rather than assumed.
    let unpacked = install_root.join("apps").join("desktop").join("dist");
    let target = find_executable(&unpacked)
        .ok_or_else(|| format!("no Marvi executable under {}", unpacked.display()))?;

    // `-Stop`, and a count checked at the end: without both, a shortcut that
    // fails to save leaves PowerShell's exit code at zero and the installer
    // reports a shortcut it never created.
    let script = format!(
        "$ErrorActionPreference = 'Stop'; \
         $shell = New-Object -ComObject WScript.Shell; \
         $made = 0; \
         foreach ($dir in @([Environment]::GetFolderPath('Desktop'), \
             (Join-Path $env:APPDATA 'Microsoft\\Windows\\Start Menu\\Programs'))) {{ \
           if (-not (Test-Path $dir)) {{ continue }} \
           $path = Join-Path $dir 'Marvi OS.lnk'; \
           $link = $shell.CreateShortcut($path); \
           $link.TargetPath = '{target}'; \
           $link.WorkingDirectory = '{workdir}'; \
           $link.Description = 'Marvi OS'; \
           $link.Save(); \
           if (-not (Test-Path $path)) {{ throw \"could not write $path\" }} \
           $made++; \
           Write-Output \"shortcut: $path\" \
         }} \
         if ($made -eq 0) {{ throw 'no shortcut location was writable' }}",
        target = plain(&target),
        workdir = plain(target.parent().unwrap_or(install_root))
    );
    crate::util::run_powershell(
        &script,
        install_root,
        Duration::from_secs(60),
        progress,
    )
}

/// Find the built Electron executable without hardcoding the product name.
#[cfg(windows)]
fn find_executable(unpacked: &Path) -> Option<PathBuf> {
    let entries = std::fs::read_dir(unpacked).ok()?;
    for entry in entries.filter_map(Result::ok) {
        let path = entry.path();
        if path.is_dir() && path.file_name()?.to_string_lossy().contains("unpacked") {
            let exe = std::fs::read_dir(&path)
                .ok()?
                .filter_map(Result::ok)
                .map(|e| e.path())
                .find(|p| {
                    p.extension().is_some_and(|e| e == "exe")
                        // Electron ships helper executables next to the app.
                        && !p.file_name().is_some_and(|n| {
                            let n = n.to_string_lossy().to_lowercase();
                            n.contains("crashpad") || n.contains("elevate")
                        })
                });
            if exe.is_some() {
                return exe;
            }
        }
    }
    None
}

#[cfg(not(windows))]
pub fn install_cli_shim(
    install_root: &Path,
    state_dir: &Path,
    progress: &mut dyn FnMut(&str),
) -> Result<(), String> {
    write_shim(install_root, state_dir, progress).map(|_| ())
}

#[cfg(not(windows))]
fn write_shim(
    install_root: &Path,
    state_dir: &Path,
    progress: &mut dyn FnMut(&str),
) -> Result<PathBuf, String> {
    let bin = bin_dir(state_dir);
    std::fs::create_dir_all(&bin).map_err(|e| format!("could not create {bin:?}: {e}"))?;
    let uv = managed_tool_path(state_dir, Tool::Uv);
    let shim = bin.join("marvi");
    std::fs::write(
        &shim,
        format!(
            "#!/bin/sh\n# Generated by the Marvi installer.\nexec \"{uv}\" run --project \"{root}/services/gateway\" marvi \"$@\"\n",
            uv = uv.display(),
            root = install_root.display()
        ),
    )
    .map_err(|e| format!("could not write {shim:?}: {e}"))?;
    #[cfg(unix)]
    {
        use std::os::unix::fs::PermissionsExt;
        let mut perms = std::fs::metadata(&shim).map_err(|e| e.to_string())?.permissions();
        perms.set_mode(0o755);
        let _ = std::fs::set_permissions(&shim, perms);
    }
    progress(&format!("installed the marvi command to {}", shim.display()));
    progress(&format!("add {} to your PATH", bin.display()));
    Ok(bin)
}

#[cfg(not(windows))]
pub fn create_shortcuts(_install_root: &Path, _progress: &mut dyn FnMut(&str)) -> Result<(), String> {
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn the_shim_points_at_the_checkout_not_at_a_copy() {
        // The regression: an installer that copies the CLI leaves yesterday's
        // version behind after an update, and the user runs it for weeks.
        let tmp = std::env::temp_dir().join(format!("marvi-handoff-{}", std::process::id()));
        let state = tmp.join("state");
        let root = tmp.join("checkout");
        std::fs::create_dir_all(&root).unwrap();

        // `write_shim`, not `install_cli_shim`: the latter also edits the
        // user's PATH, which a unit test has no business doing.
        write_shim(&root, &state, &mut |_| {}).expect("no shim written");

        let shim = bin_dir(&state).join(if cfg!(windows) { "marvi.cmd" } else { "marvi" });
        let body = std::fs::read_to_string(&shim).expect("no shim written");
        assert!(body.contains("services"), "the shim does not run the checkout");
        assert!(body.contains(&root.display().to_string()));

        let _ = std::fs::remove_dir_all(&tmp);
    }
}
