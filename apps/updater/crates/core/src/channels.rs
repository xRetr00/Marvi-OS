//! Update channel: the single knob the user flips between the safe default
//! (`Release`, opt-out) and the opt-in `Nightly` channel that tracks `main`.

use std::fmt;

use serde::{Deserialize, Serialize};

/// The two supported update channels.
///
/// - `Release` (default, opt-out): updates to the latest signed `v*` tag.
///   Never fast-forwards a moving branch.
/// - `Nightly` (opt-in): fast-forwards `origin/main` and runs whatever is there.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash, Serialize, Deserialize)]
#[serde(rename_all = "lowercase")]
pub enum Channel {
    Release,
    #[serde(alias = "dev")]
    Nightly,
}

impl Default for Channel {
    fn default() -> Self {
        Channel::Release
    }
}

impl Channel {
    /// Parse a channel label. Accepts the canonical names plus the aliases a
    /// user might type. Returns `None` for anything unknown, so callers fail
    /// closed rather than guessing.
    pub fn parse(s: &str) -> Option<Channel> {
        match s.trim().to_ascii_lowercase().as_str() {
            "release" | "stable" => Some(Channel::Release),
            "nightly" | "dev" | "development" | "main" => Some(Channel::Nightly),
            _ => None,
        }
    }

    pub fn as_str(self) -> &'static str {
        match self {
            Channel::Release => "release",
            Channel::Nightly => "nightly",
        }
    }

    /// The tracked git ref for this channel. `Release` has no branch (it
    /// follows tags); `Nightly` follows `main`.
    pub fn branch(self) -> Option<&'static str> {
        match self {
            Channel::Release => None,
            Channel::Nightly => Some("main"),
        }
    }
}

impl fmt::Display for Channel {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.write_str(self.as_str())
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn default_is_release() {
        assert_eq!(Channel::default(), Channel::Release);
    }

    #[test]
    fn parses_canonical_and_alias_names() {
        assert_eq!(Channel::parse("release"), Some(Channel::Release));
        assert_eq!(Channel::parse("STABLE"), Some(Channel::Release));
        assert_eq!(Channel::parse("nightly"), Some(Channel::Nightly));
        assert_eq!(Channel::parse("dev"), Some(Channel::Nightly));
        assert_eq!(Channel::parse("main"), Some(Channel::Nightly));
        assert_eq!(Channel::parse("Main"), Some(Channel::Nightly));
        assert_eq!(Channel::Nightly.as_str(), "nightly");
    }

    #[test]
    fn migrates_the_legacy_serialized_dev_name() {
        assert_eq!(
            serde_json::from_str::<Channel>(r#""dev""#).unwrap(),
            Channel::Nightly
        );
        assert_eq!(serde_json::to_string(&Channel::Nightly).unwrap(), r#""nightly""#);
    }

    #[test]
    fn rejects_unknown_labels() {
        assert_eq!(Channel::parse(""), None);
        assert_eq!(Channel::parse("banana"), None);
        assert_eq!(Channel::parse("master"), None);
    }
}
