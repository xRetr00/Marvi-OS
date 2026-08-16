//! Release-tag resolution for the `Release` channel.
//!
//! Releases are `v<semver>` tags (see `scripts/release.ps1`). The release
//! channel updates to the newest tag, preferring stable versions and falling
//! back to prereleases only when no stable tag exists.

use semver::Version;

/// If `name` is a `v<semver>` tag, return its parsed version.
pub fn parse_release_tag(name: &str) -> Option<Version> {
    let raw = name.strip_prefix('v')?;
    Version::parse(raw).ok()
}

/// `a` is preferable to `b`: stable beats prerelease regardless of number,
/// otherwise the higher version wins.
fn better_than(a: &Version, b: &Version) -> bool {
    match (a.pre.is_empty(), b.pre.is_empty()) {
        (true, false) => true,
        (false, true) => false,
        _ => a > b,
    }
}

/// Select the newest release tag. Returns `(tag_name, version)`.
pub fn latest(tags: impl IntoIterator<Item = String>) -> Option<(String, Version)> {
    let mut best: Option<(String, Version)> = None;
    for name in tags {
        let Some(version) = parse_release_tag(&name) else {
            continue;
        };
        let take = match &best {
            None => true,
            Some((_, best_version)) => better_than(&version, best_version),
        };
        if take {
            best = Some((name, version));
        }
    }
    best
}

#[cfg(test)]
mod tests {
    use super::*;

    fn versions(tags: &[&str]) -> Option<(String, Version)> {
        latest(tags.iter().map(|s| s.to_string()))
    }

    #[test]
    fn ignores_non_release_tags() {
        assert!(versions(&["not-a-tag", "main", "v"]).is_none());
    }

    #[test]
    fn picks_highest_stable_semver() {
        let (tag, ver) = versions(&["v0.9.0", "v1.2.0", "v1.1.0"]).unwrap();
        assert_eq!(tag, "v1.2.0");
        assert_eq!(ver, Version::parse("1.2.0").unwrap());
    }

    #[test]
    fn prefers_stable_over_higher_prerelease() {
        let (tag, _) = versions(&["v1.1.0-beta.1", "v1.0.0"]).unwrap();
        assert_eq!(tag, "v1.0.0");
    }

    #[test]
    fn falls_back_to_prerelease_when_nothing_stable() {
        let (tag, _) = versions(&["v0.1.0-dev.0", "v0.1.0-dev.1"]).unwrap();
        assert_eq!(tag, "v0.1.0-dev.1");
    }

    #[test]
    fn handles_semver_numeric_order() {
        let (tag, _) = versions(&["v2.0.0", "v10.0.0"]).unwrap();
        assert_eq!(tag, "v10.0.0");
    }
}
