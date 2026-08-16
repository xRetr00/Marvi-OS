//! Result marker written for the relaunched app to consume once.
//!
//! The shape mirrors `UpdateResult` in `apps/desktop/src/shared/runtime.ts` so
//! the Electron side can `consumeUpdateResult` without changes. Written as
//! plain UTF-8 (no BOM) so `JSON.parse` on the Electron side never trips over
//! the byte-order mark that broke the PowerShell updater.

use std::path::Path;

use serde::{Deserialize, Serialize};

use crate::util::iso8601_utc;

pub const RESULT_FILE: &str = ".marvi-update-result.json";

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(rename_all = "camelCase")]
pub struct UpdateResult {
    pub status: String,
    pub message: String,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub from: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub to: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub branch: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub channel: Option<String>,
    #[serde(skip_serializing_if = "Option::is_none")]
    pub finished_at: Option<String>,
}

impl UpdateResult {
    pub fn new(status: &str, message: impl Into<String>) -> Self {
        UpdateResult {
            status: status.to_string(),
            message: message.into(),
            from: None,
            to: None,
            branch: None,
            channel: None,
            finished_at: Some(iso8601_utc()),
        }
    }

    pub fn with_range(mut self, from: &str, to: &str) -> Self {
        self.from = Some(from.to_string());
        self.to = Some(to.to_string());
        self
    }

    pub fn with_channel(mut self, channel: crate::channels::Channel) -> Self {
        self.channel = Some(channel.as_str().to_string());
        self
    }

    pub fn with_branch(mut self, branch: Option<&str>) -> Self {
        self.branch = branch.map(|s| s.to_string());
        self
    }
}

pub fn result_path(state_dir: &Path) -> std::path::PathBuf {
    state_dir.join(RESULT_FILE)
}

/// Write the result, plain UTF-8, no BOM.
pub fn write_result(state_dir: &Path, result: &UpdateResult) -> std::io::Result<()> {
    std::fs::create_dir_all(state_dir)?;
    let json = serde_json::to_string_pretty(result).unwrap();
    std::fs::write(result_path(state_dir), json)
}

/// Read and clear the result, mirroring the Electron `consumeUpdateResult`
/// contract. A corrupt file is cleared rather than re-announced forever.
pub fn read_result(state_dir: &Path) -> Option<UpdateResult> {
    let path = result_path(state_dir);
    let parsed = std::fs::read_to_string(&path)
        .ok()
        .map(|raw| raw.strip_prefix('\u{feff}').unwrap_or(&raw).to_string())
        .and_then(|text| serde_json::from_str::<UpdateResult>(&text).ok());
    let _ = std::fs::remove_file(path);
    parsed
}

#[cfg(test)]
mod tests {
    use super::*;
    use tempfile::TempDir;

    #[test]
    fn writes_and_reads_back_once() {
        let dir = TempDir::new().unwrap();
        let state = dir.path();
        let result = UpdateResult::new("ok", "Updated successfully.").with_range("a", "b");
        write_result(state, &result).unwrap();

        let first = read_result(state).unwrap();
        assert_eq!(first.status, "ok");
        assert_eq!(first.from.as_deref(), Some("a"));
        assert_eq!(first.to.as_deref(), Some("b"));

        // Consumed: a second read finds nothing.
        assert!(read_result(state).is_none());
    }

    #[test]
    fn clears_corrupt_results_instead_of_crashing() {
        let dir = TempDir::new().unwrap();
        let state = dir.path();
        std::fs::create_dir_all(state).unwrap();
        std::fs::write(result_path(state), "{ not json").unwrap();

        assert!(read_result(state).is_none());
        assert!(!result_path(state).exists());
    }

    #[test]
    fn tolerates_a_utf8_bom() {
        let dir = TempDir::new().unwrap();
        let state = dir.path();
        std::fs::create_dir_all(state).unwrap();
        let json = serde_json::to_string(&UpdateResult::new("ok", "hi")).unwrap();
        std::fs::write(result_path(state), format!("\u{feff}{json}")).unwrap();

        assert_eq!(read_result(state).unwrap().status, "ok");
    }
}
