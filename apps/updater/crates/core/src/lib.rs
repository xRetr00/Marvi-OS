//! Marvi OS updater/installer core.
//!
//! Headless logic with no GUI or Tauri dependency, so it can be unit-tested
//! against real `git` binaries and a fake build runner. The Tauri shell
//! (`marvi-updater`) is a thin adapter over this crate.

pub mod builder;
pub mod channels;
pub mod check;
pub mod git;
pub mod install;
pub mod marker;
pub mod result;
pub mod tags;
pub mod update;
pub mod util;

pub use builder::{BuildRunner, NpmBuildRunner};
pub use channels::Channel;
pub use check::{CheckOutcome, check};
pub use install::{InstallConfig, InstallOutcome, install};
pub use marker::{Marker, clear_marker, read_marker, write_marker};
pub use result::{UpdateResult, read_result, write_result};
pub use update::{UpdateConfig, UpdateOutcome, run_update};

/// The state directory shared by the Electron app and the updater, both of
/// which resolve it from `%LOCALAPPDATA%`. Kept as one source of truth here
/// and mirrored by `updater.ts` so the two never drift. The name matches the
/// existing `updateStateDir` ("Marvi OS" with a space).
pub const STATE_DIR_NAME: &str = "Marvi OS";

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
