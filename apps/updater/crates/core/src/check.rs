//! Read-only update check: report what an update *would* do without applying
//! anything or quitting the app. Fixes the missing "check" read path that the
//! architecture promised but the PowerShell updater never implemented.

use std::path::Path;

use serde::Serialize;

use crate::channels::Channel;
use crate::git;
use crate::tags;

#[derive(Debug, Clone, Serialize)]
#[serde(rename_all = "camelCase")]
pub struct CheckOutcome {
    pub channel: String,
    pub available: bool,
    pub up_to_date: bool,
    pub current: Option<String>,
    pub target: Option<String>,
    pub target_ref: Option<String>,
    pub behind_by: u64,
    pub signed: Option<bool>,
    pub error: Option<String>,
}

/// Determine the update target for a checkout without mutating it.
///
/// Performs a non-destructive `git fetch` (updates remote-tracking refs, never
/// the working tree) so `behind_by` is accurate.
pub fn check(root: &Path, channel: Channel) -> CheckOutcome {
    let base = || CheckOutcome {
        channel: channel.as_str().to_string(),
        available: false,
        up_to_date: false,
        current: None,
        target: None,
        target_ref: None,
        behind_by: 0,
        signed: None,
        error: None,
    };

    let Ok(current) = git::current_commit(root) else {
        return CheckOutcome {
            error: Some("not a usable git checkout".to_string()),
            ..base()
        };
    };

    match channel {
        Channel::Release => {
            let Ok(remote_tags) = git::ls_remote_tags(root) else {
                return CheckOutcome {
                    current: Some(current),
                    error: Some("could not reach the update server".to_string()),
                    ..base()
                };
            };
            let Some((tag, _version)) = tags::latest(remote_tags) else {
                return CheckOutcome {
                    current: Some(current),
                    error: Some("no release tags found on origin".to_string()),
                    ..base()
                };
            };
            // Fetch tag objects so the commit can be resolved locally. This
            // updates remote-tracking refs only, never the working tree.
            if git::fetch_tags(root).is_err() {
                return CheckOutcome {
                    current: Some(current),
                    error: Some("could not fetch release tags".to_string()),
                    ..base()
                };
            }
            let Ok(target) = git::resolve_commit(root, &tag) else {
                return CheckOutcome {
                    current: Some(current),
                    error: Some("could not resolve the release tag".to_string()),
                    ..base()
                };
            };
            let up_to_date = current == target;
            let signed = git::verify_tag(root, &tag)
                .ok()
                .map(|s| matches!(s, git::SignatureStatus::Valid));
            CheckOutcome {
                available: !up_to_date,
                up_to_date,
                current: Some(current),
                target: Some(target),
                target_ref: Some(tag),
                behind_by: if up_to_date { 0 } else { 1 },
                signed,
                ..base()
            }
        }
        Channel::Dev => {
            let Ok(Some(target)) = git::ls_remote_branch(root, "main") else {
                return CheckOutcome {
                    current: Some(current),
                    error: Some("could not reach origin/main".to_string()),
                    ..base()
                };
            };
            // Fetch so the commit count is meaningful; non-destructive.
            if git::fetch_origin(root).is_err() {
                return CheckOutcome {
                    current: Some(current),
                    target: Some(target),
                    target_ref: Some("origin/main".to_string()),
                    error: Some("could not fetch origin".to_string()),
                    ..base()
                };
            }
            let behind_by = git::commit_count_behind(root, &current, &target).unwrap_or(0);
            let up_to_date = current == target;
            CheckOutcome {
                available: !up_to_date,
                up_to_date,
                current: Some(current),
                target: Some(target),
                target_ref: Some("origin/main".to_string()),
                behind_by,
                signed: None,
                ..base()
            }
        }
    }
}
