//! Provisioning `uv` and Node, and keeping them current.
//!
//! Marvi is a git checkout driven by a Python service and a Node build, so
//! neither toolchain is optional. Leaving them to the user produced the failure
//! that opened Phase 10: a GUI-launched Electron does not inherit the PATH a
//! terminal has, so a `uv` installed afterwards is one the app cannot see, and
//! every symptom of that looked identical to every other startup failure.
//!
//! So the installer owns them. They are installed **into the state directory**
//! rather than system-wide:
//!
//! * an uninstall takes them with it, instead of leaving tools behind;
//! * a machine-wide `uv` that someone else manages is not overwritten;
//! * the path is known, so it can be handed to the app explicitly rather than
//!   hoped for on PATH.
//!
//! Checked on every install *and* every update, because a release can need a
//! newer toolchain than the one that installed the last release, and finding
//! that out during the build is finding out too late.
//!
//! **Marvi installs its own copies even when the tools are already on PATH.**
//! That was not the original design — reusing a working tool looked like it
//! saved a download — but the PATH a developer's terminal has is not the PATH a
//! GUI-launched app inherits, so "found during install" and "usable at runtime"
//! are different questions and only the second one matters. A copy at a path
//! Marvi chose is one it can always hand to a child process. What is on PATH is
//! still reported, because it is useful to see; it just is not relied on.

use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::Duration;

#[cfg(not(windows))]
use crate::util::run_shell_reporting;
#[cfg(windows)]
use crate::util::run_powershell;

/// How long a toolchain download is allowed to take before it is a failure
/// rather than a slow connection.
const INSTALL_TIMEOUT: Duration = Duration::from_secs(600);

/// The minimum Node the desktop build needs, as (major, minor).
///
/// A major-only check was not enough: v22.11.0 satisfied "at least 22" and
/// still failed every dependency, which require `>=22.12.0`. The dependency
/// that actually broke needs `require()` of an ES module, which Node supports
/// from 22.12 and not before — a difference of one minor version that a major
/// comparison cannot see.
pub const NODE_MINIMUM: (u32, u32) = (22, 12);

/// The `uv` release to install. Pinned for the same reason `NODE_VERSION` is:
/// an installer that silently follows `latest` is an installer whose result
/// depends on the day it ran.
pub const UV_VERSION: &str = "0.12.5";

/// One of the two toolchains Marvi cannot run without.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum Tool {
    Uv,
    Node,
}

impl Tool {
    pub fn name(self) -> &'static str {
        match self {
            Tool::Uv => "uv",
            Tool::Node => "node",
        }
    }

    /// The executable name, including the Windows extension.
    fn executable(self) -> &'static str {
        match self {
            Tool::Uv => {
                if cfg!(windows) {
                    "uv.exe"
                } else {
                    "uv"
                }
            }
            Tool::Node => {
                if cfg!(windows) {
                    "node.exe"
                } else {
                    "node"
                }
            }
        }
    }
}

/// What was found, and where.
#[derive(Debug, Clone)]
pub struct ToolStatus {
    pub tool: &'static str,
    pub found: bool,
    pub path: Option<PathBuf>,
    pub version: String,
    /// True when Marvi installed it, rather than finding one already present.
    pub managed: bool,
    pub detail: String,
}

/// Where Marvi keeps the toolchains it installed itself.
pub fn toolchain_dir(state_dir: &Path) -> PathBuf {
    state_dir.join("toolchain")
}

/// Where Marvi's own copy of a tool lives, installed or not.
pub fn managed_tool_path(state_dir: &Path, tool: Tool) -> PathBuf {
    let base = toolchain_dir(state_dir).join(tool.name());
    match tool {
        Tool::Uv => base.join(tool.executable()),
        // The Node archive unpacks with the binary at its root on Windows and
        // under bin/ elsewhere.
        Tool::Node => {
            if cfg!(windows) {
                base.join(tool.executable())
            } else {
                base.join("bin").join(tool.executable())
            }
        }
    }
}

fn probe_version(exe: &Path) -> Option<String> {
    let output = Command::new(exe).arg("--version").output().ok()?;
    if !output.status.success() {
        return None;
    }
    Some(String::from_utf8_lossy(&output.stdout).trim().to_string())
}

fn on_path(tool: Tool) -> Option<(PathBuf, String)> {
    let finder = if cfg!(windows) { "where" } else { "which" };
    let output = Command::new(finder).arg(tool.name()).output().ok()?;
    if !output.status.success() {
        return None;
    }
    let first = String::from_utf8_lossy(&output.stdout)
        .lines()
        .next()?
        .trim()
        .to_string();
    if first.is_empty() {
        return None;
    }
    let path = PathBuf::from(first);
    let version = probe_version(&path)?;
    Some((path, version))
}

/// (major, minor) from a `vX.Y.Z` string.
fn node_version(version: &str) -> Option<(u32, u32)> {
    let mut parts = version.trim_start_matches('v').split('.');
    let major = parts.next()?.parse().ok()?;
    let minor = parts.next().unwrap_or("0").parse().unwrap_or(0);
    Some((major, minor))
}

fn node_too_old(version: &str) -> bool {
    node_version(version).is_some_and(|found| found < NODE_MINIMUM)
}

/// Look for one tool: Marvi's own copy first, then whatever is on PATH.
pub fn status(state_dir: &Path, tool: Tool) -> ToolStatus {
    let managed = managed_tool_path(state_dir, tool);
    if let Some(version) = probe_version(&managed) {
        let too_old = tool == Tool::Node && node_too_old(&version);
        return ToolStatus {
            tool: tool.name(),
            found: !too_old,
            path: Some(managed),
            version: version.clone(),
            managed: true,
            detail: if too_old {
                format!(
                    "{version} is older than the required v{}.{}",
                    NODE_MINIMUM.0, NODE_MINIMUM.1
                )
            } else {
                "installed by Marvi".to_string()
            },
        };
    }

    if let Some((path, version)) = on_path(tool) {
        // Reported, not relied on: `found` stays false so the installer
        // provisions a copy at a path it controls. See the module comment.
        return ToolStatus {
            tool: tool.name(),
            found: false,
            path: Some(path),
            version: version.clone(),
            managed: false,
            detail: "on PATH, but not one Marvi controls".to_string(),
        };
    }

    ToolStatus {
        tool: tool.name(),
        found: false,
        path: None,
        version: String::new(),
        managed: false,
        detail: "not found".to_string(),
    }
}

/// Both toolchains, for the installer UI and for `check`.
pub fn toolchain_status(state_dir: &Path) -> Vec<ToolStatus> {
    vec![status(state_dir, Tool::Uv), status(state_dir, Tool::Node)]
}

fn uv_archive_url() -> Result<String, String> {
    let triple = match (std::env::consts::OS, std::env::consts::ARCH) {
        ("windows", "x86_64") => "x86_64-pc-windows-msvc",
        ("windows", "aarch64") => "aarch64-pc-windows-msvc",
        ("linux", "x86_64") => "x86_64-unknown-linux-gnu",
        ("linux", "aarch64") => "aarch64-unknown-linux-gnu",
        ("macos", "x86_64") => "x86_64-apple-darwin",
        ("macos", "aarch64") => "aarch64-apple-darwin",
        (os, arch) => return Err(format!("no uv build for {os}/{arch}")),
    };
    let extension = if cfg!(windows) { "zip" } else { "tar.gz" };
    Ok(format!(
        "https://github.com/astral-sh/uv/releases/download/{UV_VERSION}/uv-{triple}.{extension}"
    ))
}

fn install_uv(state_dir: &Path, progress: &mut dyn FnMut(&str)) -> Result<PathBuf, String> {
    let target = toolchain_dir(state_dir).join("uv");
    std::fs::create_dir_all(&target).map_err(|e| format!("could not create {target:?}: {e}"))?;
    progress(&format!("installing uv {UV_VERSION}"));

    // The release archive, not `install.ps1`.
    //
    // The vendor script calls `Get-ExecutionPolicy`, and on a host where
    // PSModulePath has been narrowed that cmdlet cannot autoload — the script
    // dies with "the module could not be loaded" before it downloads anything.
    // That is a real failure (it broke the release build) and it is not
    // something this code can fix from the outside, because PowerShell
    // recomputes PSModulePath at startup.
    //
    // Fetching the archive ourselves removes the dependency rather than
    // negotiating with it: the same two operations the Node install already
    // uses, and nothing that needs a module to load.
    let url = uv_archive_url()?;
    #[cfg(windows)]
    {
        let script = format!(
            "$ErrorActionPreference='Stop'; \
             $tmp=Join-Path $env:TEMP 'marvi-uv-{suffix}.zip'; \
             Invoke-WebRequest -Uri '{url}' -OutFile $tmp; \
             Expand-Archive -Path $tmp -DestinationPath '{target}' -Force; \
             Remove-Item $tmp",
            suffix = crate::util::random_suffix(),
            url = url,
            target = target.display()
        );
        run_powershell(&script, state_dir, INSTALL_TIMEOUT, progress)
            .map_err(|e| format!("uv install failed: {e}"))?;
        // The Windows archive holds the executables at its root, but a future
        // release could nest them; find the binary rather than assume.
        lift_binary(&target, Tool::Uv)?;
    }
    #[cfg(not(windows))]
    {
        let command = format!(
            "set -e; mkdir -p '{target}'; curl -Ls '{url}' | tar -xz -C '{target}'",
            target = target.display(),
            url = url
        );
        run_shell_reporting(&command, state_dir, INSTALL_TIMEOUT, progress)
            .map_err(|e| format!("uv install failed: {e}"))?;
        lift_binary(&target, Tool::Uv)?;
    }

    let exe = managed_tool_path(state_dir, Tool::Uv);
    if probe_version(&exe).is_none() {
        return Err("uv installed but does not run".to_string());
    }
    Ok(exe)
}

/// Move a tool's executable to the root of `dir` if the archive nested it.
///
/// Publishers move things between releases; the managed path is a contract with
/// the rest of Marvi, so the binary is put where that contract says it is.
fn lift_binary(dir: &Path, tool: Tool) -> Result<(), String> {
    let expected = dir.join(tool.executable());
    if expected.is_file() {
        return Ok(());
    }
    let found = walk_for(dir, tool.executable(), 3)
        .ok_or_else(|| format!("{} is not in the archive", tool.executable()))?;
    std::fs::rename(&found, &expected)
        .map_err(|e| format!("could not place {}: {e}", tool.executable()))?;
    Ok(())
}

fn walk_for(dir: &Path, name: &str, depth: usize) -> Option<PathBuf> {
    let entries = std::fs::read_dir(dir).ok()?;
    let mut directories = Vec::new();
    for entry in entries.filter_map(Result::ok) {
        let path = entry.path();
        if path.is_file() && path.file_name().is_some_and(|n| n == name) {
            return Some(path);
        }
        if path.is_dir() {
            directories.push(path);
        }
    }
    if depth == 0 {
        return None;
    }
    directories.into_iter().find_map(|d| walk_for(&d, name, depth - 1))
}

fn node_archive_url(version: &str) -> Result<String, String> {
    let (platform, extension) = match (std::env::consts::OS, std::env::consts::ARCH) {
        ("windows", "x86_64") => ("win-x64", "zip"),
        ("windows", "aarch64") => ("win-arm64", "zip"),
        ("linux", "x86_64") => ("linux-x64", "tar.xz"),
        ("linux", "aarch64") => ("linux-arm64", "tar.xz"),
        ("macos", "x86_64") => ("darwin-x64", "tar.gz"),
        ("macos", "aarch64") => ("darwin-arm64", "tar.gz"),
        (os, arch) => return Err(format!("no Node build for {os}/{arch}")),
    };
    Ok(format!(
        "https://nodejs.org/dist/{version}/node-{version}-{platform}.{extension}"
    ))
}

fn install_node(
    state_dir: &Path,
    version: &str,
    progress: &mut dyn FnMut(&str),
) -> Result<PathBuf, String> {
    let base = toolchain_dir(state_dir).join("node");
    let url = node_archive_url(version)?;
    std::fs::create_dir_all(&base).map_err(|e| format!("could not create {base:?}: {e}"))?;
    progress(&format!("installing Node {version}"));

    // Unpacked into a staging directory and moved into place, so an
    // interrupted download never leaves something that looks installed.
    let staging = base.with_extension(crate::util::random_suffix());
    #[cfg(windows)]
    let outcome = {
        // A unique temp name: two installs running at once would otherwise
        // download over each other's archive.
        let script = format!(
            "$ErrorActionPreference='Stop'; \
             $tmp=Join-Path $env:TEMP 'marvi-node-{suffix}.zip'; \
             Invoke-WebRequest -Uri '{url}' -OutFile $tmp; \
             Expand-Archive -Path $tmp -DestinationPath '{staging}' -Force; \
             Remove-Item $tmp",
            suffix = crate::util::random_suffix(),
            url = url,
            staging = staging.display()
        );
        run_powershell(&script, state_dir, INSTALL_TIMEOUT, progress)
    };
    #[cfg(not(windows))]
    let outcome = {
        let command = format!(
            "set -e; mkdir -p '{staging}'; curl -Ls '{url}' | tar -x -C '{staging}' --strip-components=0",
            staging = staging.display(),
            url = url
        );
        run_shell_reporting(&command, state_dir, INSTALL_TIMEOUT, progress)
    };
    outcome.map_err(|e| {
        let _ = std::fs::remove_dir_all(&staging);
        format!("Node download failed: {e}")
    })?;

    // The archive contains a single versioned directory; lift its contents up.
    let inner = std::fs::read_dir(&staging)
        .map_err(|e| format!("could not read the Node archive: {e}"))?
        .filter_map(Result::ok)
        .map(|entry| entry.path())
        .find(|path| path.is_dir());
    let source = inner.unwrap_or_else(|| staging.clone());

    let _ = std::fs::remove_dir_all(&base);
    std::fs::rename(&source, &base).map_err(|e| format!("could not place Node: {e}"))?;
    let _ = std::fs::remove_dir_all(&staging);

    let exe = managed_tool_path(state_dir, Tool::Node);
    if probe_version(&exe).is_none() {
        return Err("Node installed but does not run".to_string());
    }
    Ok(exe)
}

/// Make sure both toolchains are present and usable.
///
/// Called on install and on every update. Returns the directories to prepend to
/// `PATH` for the build that follows, so the build uses what was just
/// provisioned rather than hoping the shell agrees.
pub fn ensure_toolchain(
    state_dir: &Path,
    node_version: &str,
    progress: &mut dyn FnMut(&str),
) -> Result<Vec<PathBuf>, String> {
    let mut extra_paths = Vec::new();

    for tool in [Tool::Uv, Tool::Node] {
        let found = status(state_dir, tool);
        let path = if found.found {
            progress(&format!(
                "{} {} ({})",
                found.tool, found.version, found.detail
            ));
            managed_tool_path(state_dir, tool)
        } else {
            if let Some(other) = found.path.as_ref() {
                // Worth saying out loud: the user has the tool, and Marvi is
                // downloading one anyway. Silence there looks like a bug.
                progress(&format!(
                    "{} {} found at {} — installing Marvi's own copy so the app \
                     can find it too",
                    found.tool,
                    found.version,
                    other.display()
                ));
            }
            let installed = match tool {
                Tool::Uv => install_uv(state_dir, progress)?,
                Tool::Node => install_node(state_dir, node_version, progress)?,
            };
            progress(&format!("{} ready", tool.name()));
            installed
        };
        if let Some(parent) = path.parent() {
            extra_paths.push(parent.to_path_buf());
        }
    }

    Ok(extra_paths)
}

/// Prepend directories to a `PATH` value.
///
/// The build runs as a child process, and a child that cannot see the toolchain
/// Marvi just installed is the same failure this module exists to prevent.
pub fn prepend_path(extra: &[PathBuf], current: Option<String>) -> String {
    let separator = if cfg!(windows) { ";" } else { ":" };
    let mut parts: Vec<String> = extra.iter().map(|p| p.display().to_string()).collect();
    if let Some(existing) = current {
        parts.push(existing);
    }
    parts.join(separator)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_tool_on_path_does_not_satisfy_the_requirement() {
        // The regression this guards: v0.1.3 found the developer's own uv and
        // Node, installed neither, and the GUI-launched app — which inherits a
        // different PATH — could not run either of them.
        let empty = std::env::temp_dir().join("marvi-toolchain-empty");
        let _ = std::fs::remove_dir_all(&empty);
        for tool in [Tool::Uv, Tool::Node] {
            let found = status(&empty, tool);
            assert!(!found.found, "{} must be installed, not borrowed", tool.name());
            assert!(!found.managed);
        }
    }

    #[test]
    fn node_versions_are_compared_by_major_and_minor() {
        // The regression: v22.11.0 shipped, satisfied a major-only check, and
        // could not build the app. Every Electron and Vite package requires
        // >=22.12.0, and the one that broke needs `require()` of an ES module,
        // which Node supports from 22.12 and not before.
        assert!(node_too_old("v22.11.0"), "22.11 cannot build the app");
        assert!(!node_too_old("v22.12.0"));
        assert!(!node_too_old("v22.23.2"));
        assert!(!node_too_old("v24.12.0"));
        assert!(node_too_old("v20.19.0"));
        assert_eq!(node_version("v22.11.0"), Some((22, 11)));
        assert_eq!(node_version("nonsense"), None);
    }

    #[test]
    fn the_version_we_provision_satisfies_our_own_minimum() {
        // The pin and the floor are two constants in two files, and shipping a
        // pin below the floor is exactly what v0.2.0 did.
        assert!(!node_too_old(crate::install::NODE_VERSION));
    }

    #[test]
    fn every_supported_platform_has_an_archive() {
        // A missing mapping should fail here rather than halfway through an
        // install on someone's machine.
        let url = node_archive_url("v22.11.0");
        if cfg!(any(target_os = "windows", target_os = "linux", target_os = "macos")) {
            let url = url.expect("this platform should be supported");
            assert!(url.starts_with("https://nodejs.org/dist/v22.11.0/"));
        }
    }

    #[test]
    fn path_is_prepended_not_replaced() {
        let extra = vec![PathBuf::from("/marvi/uv")];
        let joined = prepend_path(&extra, Some("/usr/bin".to_string()));
        assert!(joined.starts_with("/marvi/uv"));
        assert!(joined.contains("/usr/bin"));
    }
}
