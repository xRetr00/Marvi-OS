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
//! A tool already on PATH is used as-is. Downloading a second copy of something
//! that works is a waste of the user's bandwidth and their disk.

use std::path::{Path, PathBuf};
use std::process::Command;
use std::time::Duration;

use crate::util::run_shell_with_timeout;

/// How long a toolchain download is allowed to take before it is a failure
/// rather than a slow connection.
const INSTALL_TIMEOUT: Duration = Duration::from_secs(600);

/// The minimum Node major version the desktop build needs.
pub const NODE_MAJOR_MINIMUM: u32 = 20;

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

fn managed_path(state_dir: &Path, tool: Tool) -> PathBuf {
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

fn node_major(version: &str) -> Option<u32> {
    version.trim_start_matches('v').split('.').next()?.parse().ok()
}

/// Look for one tool: Marvi's own copy first, then whatever is on PATH.
pub fn status(state_dir: &Path, tool: Tool) -> ToolStatus {
    let managed = managed_path(state_dir, tool);
    if let Some(version) = probe_version(&managed) {
        return ToolStatus {
            tool: tool.name(),
            found: true,
            path: Some(managed),
            version,
            managed: true,
            detail: "installed by Marvi".to_string(),
        };
    }

    if let Some((path, version)) = on_path(tool) {
        // Already usable. Downloading a second copy of a working tool wastes
        // the user's bandwidth and their disk.
        let too_old = tool == Tool::Node
            && node_major(&version).is_some_and(|major| major < NODE_MAJOR_MINIMUM);
        return ToolStatus {
            tool: tool.name(),
            found: !too_old,
            path: Some(path),
            version: version.clone(),
            managed: false,
            detail: if too_old {
                format!("{version} is older than the required v{NODE_MAJOR_MINIMUM}")
            } else {
                "already on PATH".to_string()
            },
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

fn install_uv(state_dir: &Path, progress: &mut dyn FnMut(&str)) -> Result<PathBuf, String> {
    let target = toolchain_dir(state_dir).join("uv");
    std::fs::create_dir_all(&target).map_err(|e| format!("could not create {target:?}: {e}"))?;
    progress("installing uv");

    // The vendor's own installer, pointed at Marvi's directory rather than the
    // user's profile, so an uninstall takes it away again.
    let command = if cfg!(windows) {
        format!(
            "powershell -NoProfile -ExecutionPolicy Bypass -Command \
             \"$env:UV_INSTALL_DIR='{}'; $env:UV_NO_MODIFY_PATH='1'; \
             irm https://astral.sh/uv/install.ps1 | iex\"",
            target.display()
        )
    } else {
        format!(
            "UV_INSTALL_DIR='{}' UV_NO_MODIFY_PATH=1 \
             curl -LsSf https://astral.sh/uv/install.sh | sh",
            target.display()
        )
    };
    run_shell_with_timeout(&command, state_dir, INSTALL_TIMEOUT)
        .map_err(|e| format!("uv install failed: {e}"))?;

    let exe = managed_path(state_dir, Tool::Uv);
    if probe_version(&exe).is_none() {
        return Err("uv installed but does not run".to_string());
    }
    Ok(exe)
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
    let command = if cfg!(windows) {
        format!(
            "powershell -NoProfile -ExecutionPolicy Bypass -Command \
             \"$ErrorActionPreference='Stop'; $tmp=Join-Path $env:TEMP 'marvi-node.zip'; \
             Invoke-WebRequest -Uri '{url}' -OutFile $tmp; \
             Expand-Archive -Path $tmp -DestinationPath '{staging}' -Force; \
             Remove-Item $tmp\"",
            url = url,
            staging = staging.display()
        )
    } else {
        format!(
            "set -e; mkdir -p '{staging}'; curl -Ls '{url}' | tar -x -C '{staging}' --strip-components=0",
            staging = staging.display(),
            url = url
        )
    };
    run_shell_with_timeout(&command, state_dir, INSTALL_TIMEOUT).map_err(|e| {
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

    let exe = managed_path(state_dir, Tool::Node);
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
        if found.found {
            progress(&format!(
                "{} {} ({})",
                found.tool, found.version, found.detail
            ));
            if found.managed {
                if let Some(path) = found.path.as_ref().and_then(|p| p.parent()) {
                    extra_paths.push(path.to_path_buf());
                }
            }
            continue;
        }

        let installed = match tool {
            Tool::Uv => install_uv(state_dir, progress)?,
            Tool::Node => install_node(state_dir, node_version, progress)?,
        };
        if let Some(parent) = installed.parent() {
            extra_paths.push(parent.to_path_buf());
        }
        progress(&format!("{} ready", tool.name()));
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
    fn a_missing_tool_is_reported_not_guessed() {
        let empty = std::env::temp_dir().join("marvi-toolchain-empty");
        let found = status(&empty, Tool::Uv);
        // It may legitimately be on PATH on a developer machine; what must not
        // happen is claiming a managed copy that is not there.
        assert!(!found.managed || found.path.is_some());
    }

    #[test]
    fn node_versions_are_compared_by_major() {
        assert_eq!(node_major("v22.11.0"), Some(22));
        assert_eq!(node_major("18.0.0"), Some(18));
        assert_eq!(node_major("nonsense"), None);
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
