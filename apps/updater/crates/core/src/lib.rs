//! Marvi OS updater/installer core.
//!
//! Headless logic with no GUI or Tauri dependency, so it can be unit-tested
//! against real `git` binaries and a fake build runner. The Tauri shell
//! (`marvi-updater`) is a thin adapter over this crate.

pub mod builder;
pub mod channels;
pub mod check;
pub mod git;
pub mod handoff;
pub mod journal;
pub mod install;
pub mod marker;
pub mod result;
pub mod selfupdate;
pub mod singleton;
pub mod tags;
pub mod toolchain;
pub mod update;
pub mod util;

pub use builder::{BuildRunner, NpmBuildRunner};
pub use channels::Channel;
pub use check::{CheckOutcome, check};
pub use handoff::{create_shortcuts, install_cli_shim, install_essentials};
pub use journal::InstallLog;
pub use install::{InstallConfig, InstallOutcome, NODE_VERSION, install};
pub use marker::{Marker, clear_marker, read_marker, write_marker};
pub use result::{UpdateResult, read_result, write_result};
pub use singleton::{Lock, acquire, clear_install_root, find_strays, kill_tree};
pub use toolchain::{Tool, ToolStatus, ensure_toolchain, toolchain_status};
pub use update::{UpdateConfig, UpdateOutcome, run_update};

/// The state directory shared by the Electron app, the Gateway and the
/// updater, all of which resolve it from `%LOCALAPPDATA%`. Kept as one source
/// of truth here and mirrored by `updater.ts` and `marvi_gateway/paths.py` so
/// they never drift.
///
/// Hyphenated, and deliberately: models and runtime binaries already lived in
/// `Marvi-OS`, two nearly identical folder names were confusing to look at, and
/// a space in a path is a nuisance in every shell.
pub const STATE_DIR_NAME: &str = "Marvi-OS";

/// The pre-rename directory. Anything still in it is migrated on first use
/// rather than abandoned - a user's journal, memory and identity live there.
pub const LEGACY_STATE_DIR_NAME: &str = "Marvi OS";

/// Resolve the updater state directory for this machine.
///
/// Falls back to a `.marvi` directory under the user profile when
/// `LOCALAPPDATA` is unset (non-Windows hosts and unusual setups), matching
/// the Electron side's behaviour.
pub fn state_dir() -> std::path::PathBuf {
    if let Some(app_data) = std::env::var_os("LOCALAPPDATA") {
        std::path::PathBuf::from(app_data).join(STATE_DIR_NAME)
    } else if let Some(profile) = std::env::var_os("USERPROFILE") {
        std::path::PathBuf::from(profile).join(".marvi")
    } else {
        std::path::PathBuf::from(STATE_DIR_NAME)
    }
}

/// The pre-rename state directory, if this machine has one.
pub fn legacy_state_dir() -> Option<std::path::PathBuf> {
    let app_data = std::env::var_os("LOCALAPPDATA")?;
    let path = std::path::PathBuf::from(app_data).join(LEGACY_STATE_DIR_NAME);
    path.is_dir().then_some(path)
}
