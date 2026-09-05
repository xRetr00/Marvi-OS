//! Build steps, abstracted behind a trait so the update/install logic can be
//! tested against a fake without running a real `npm` build.

use std::path::{Path, PathBuf};
use std::time::Duration;

use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};

use crate::util::run_shell_reporting;

const DEPENDENCY_CACHE_SCHEMA: u8 = 1;
const DEPENDENCY_CACHE_MARKER: &str = ".marvi-dependencies.json";
const DEPENDENCY_INPUTS: &[&str] = &[
    "package-lock.json",
    "package.json",
    "apps/desktop/package.json",
];

#[derive(Debug, PartialEq, Eq, Serialize, Deserialize)]
struct DependencyFingerprint {
    schema: u8,
    node_version: String,
    npm_version: String,
    inputs: Vec<DependencyInput>,
}

#[derive(Debug, PartialEq, Eq, Serialize, Deserialize)]
struct DependencyInput {
    path: String,
    sha256: String,
}

fn cache_marker(root: &Path) -> PathBuf {
    root.join("node_modules").join(DEPENDENCY_CACHE_MARKER)
}

fn tool_version(root: &Path, command: &str) -> Result<String, String> {
    let mut output = Vec::new();
    run_shell_reporting(command, root, Duration::from_secs(30), &mut |line| {
        output.push(line.to_string());
    })?;
    output
        .last()
        .map(|line| line.trim().to_string())
        .filter(|line| !line.is_empty())
        .ok_or_else(|| format!("{command} returned no version"))
}

fn dependency_fingerprint(
    root: &Path,
    node_version: String,
    npm_version: String,
) -> Result<DependencyFingerprint, String> {
    let mut inputs = Vec::with_capacity(DEPENDENCY_INPUTS.len());
    for relative in DEPENDENCY_INPUTS {
        let bytes = std::fs::read(root.join(relative))
            .map_err(|e| format!("could not read dependency input {relative}: {e}"))?;
        inputs.push(DependencyInput {
            path: relative.to_string(),
            sha256: format!("{:x}", Sha256::digest(bytes)),
        });
    }
    Ok(DependencyFingerprint {
        schema: DEPENDENCY_CACHE_SCHEMA,
        node_version,
        npm_version,
        inputs,
    })
}

fn cache_matches(root: &Path, expected: &DependencyFingerprint) -> bool {
    if !root.join("node_modules").is_dir() {
        return false;
    }
    std::fs::read(cache_marker(root))
        .ok()
        .and_then(|bytes| serde_json::from_slice::<DependencyFingerprint>(&bytes).ok())
        .is_some_and(|actual| actual == *expected)
}

fn invalidate_cache(root: &Path) {
    let _ = std::fs::remove_file(cache_marker(root));
}

fn record_cache(root: &Path, fingerprint: &DependencyFingerprint) -> Result<(), String> {
    let marker = cache_marker(root);
    if !root.join("node_modules").is_dir() {
        return Err("npm completed without creating node_modules".to_string());
    }
    let bytes = serde_json::to_vec(fingerprint)
        .map_err(|e| format!("could not serialize dependency cache marker: {e}"))?;
    let temporary = marker.with_extension("json.tmp");
    std::fs::write(&temporary, bytes)
        .map_err(|e| format!("could not write dependency cache marker: {e}"))?;
    std::fs::rename(&temporary, &marker)
        .map_err(|e| format!("could not activate dependency cache marker: {e}"))
}

fn install_dependencies(
    root: &Path,
    fingerprint: &DependencyFingerprint,
    progress: &mut dyn FnMut(&str),
    install: &mut dyn FnMut(&mut dyn FnMut(&str)) -> Result<(), String>,
) -> Result<(), String> {
    // A failed or interrupted npm install must never leave a marker that can
    // make the next update trust its partial node_modules tree.
    invalidate_cache(root);
    progress("installing dependencies (npm ci)");
    install(progress).map_err(|e| format!("dependency installation failed: {e}"))?;
    if let Err(error) = record_cache(root, fingerprint) {
        // The cache is only an optimization. A valid install must not be
        // rejected merely because its marker could not be persisted.
        progress(&format!("dependency cache unavailable: {error}"));
    }
    Ok(())
}

fn prepare_with_commands(
    root: &Path,
    fingerprint: &DependencyFingerprint,
    progress: &mut dyn FnMut(&str),
    install: &mut dyn FnMut(&mut dyn FnMut(&str)) -> Result<(), String>,
    build: &mut dyn FnMut(&mut dyn FnMut(&str)) -> Result<(), String>,
) -> Result<(), String> {
    let reused = cache_matches(root, fingerprint);
    if reused {
        progress("reusing installed dependencies (verified cache)");
    } else {
        install_dependencies(root, fingerprint, progress, install)?;
    }

    progress("building (npm run build:unpack)");
    if let Err(first_error) = build(progress) {
        if !reused {
            return Err(format!("build failed: {first_error}"));
        }
        progress("cached dependencies failed the build; repairing cache");
        install_dependencies(root, fingerprint, progress, install)?;
        progress("building (npm run build:unpack)");
        build(progress).map_err(|retry_error| {
            format!(
                "build failed with cached dependencies: {first_error}; retry after npm ci failed: {retry_error}"
            )
        })?;
    }
    Ok(())
}

/// Runs the dependency-install and build stages inside a checkout.
///
/// The real implementation shells out to `npm`; tests substitute a fake that
/// either succeeds (marking its work) or fails, to exercise rollback.
pub trait BuildRunner {
    /// Install dependencies and build the runtime. `progress` receives a
    /// human-readable stage description for the UI/log.
    fn prepare(&mut self, root: &Path, progress: &mut dyn FnMut(&str)) -> Result<(), String>;
}

/// Real runner: `npm ci` (strict; a lockfile mismatch fails rather than being
/// silently rewritten) then `npm run build:unpack` (rebuilds both the
/// `out/` runtime and the packaged `dist/win-unpacked` app).
pub struct NpmBuildRunner {
    pub ci_timeout: Duration,
    pub build_timeout: Duration,
}

impl Default for NpmBuildRunner {
    fn default() -> Self {
        NpmBuildRunner {
            ci_timeout: Duration::from_secs(600),
            build_timeout: Duration::from_secs(1800),
        }
    }
}

impl BuildRunner for NpmBuildRunner {
    fn prepare(&mut self, root: &Path, progress: &mut dyn FnMut(&str)) -> Result<(), String> {
        let fingerprint = dependency_fingerprint(
            root,
            tool_version(root, "node --version")?,
            tool_version(root, "npm --version")?,
        )?;
        let ci_timeout = self.ci_timeout;
        let mut install = |progress: &mut dyn FnMut(&str)| {
            run_shell_reporting("npm ci", root, ci_timeout, progress)
        };
        let build_timeout = self.build_timeout;
        let mut build = |progress: &mut dyn FnMut(&str)| {
            run_shell_reporting("npm run build:unpack", root, build_timeout, progress)
        };
        prepare_with_commands(root, &fingerprint, progress, &mut install, &mut build)
    }
}

#[cfg(test)]
mod cache_tests {
    use super::*;

    fn fixture() -> tempfile::TempDir {
        let root = tempfile::tempdir().unwrap();
        std::fs::create_dir_all(root.path().join("apps/desktop")).unwrap();
        std::fs::write(root.path().join("package-lock.json"), "lock-a").unwrap();
        std::fs::write(root.path().join("package.json"), "root-a").unwrap();
        std::fs::write(root.path().join("apps/desktop/package.json"), "desktop-a").unwrap();
        root
    }

    fn fingerprint(root: &Path) -> DependencyFingerprint {
        dependency_fingerprint(root, "v22.23.2".into(), "10.9.8".into()).unwrap()
    }

    #[test]
    fn successful_install_is_reused_only_for_identical_inputs() {
        let root = fixture();
        let expected = fingerprint(root.path());
        let mut lines = Vec::new();
        let mut install = |_: &mut dyn FnMut(&str)| {
            std::fs::create_dir_all(root.path().join("node_modules")).map_err(|e| e.to_string())
        };
        install_dependencies(
            root.path(),
            &expected,
            &mut |line| lines.push(line.to_string()),
            &mut install,
        )
        .unwrap();

        assert!(cache_matches(root.path(), &expected));
        std::fs::write(root.path().join("package-lock.json"), "lock-b").unwrap();
        assert!(!cache_matches(root.path(), &fingerprint(root.path())));
    }

    #[test]
    fn tool_version_changes_invalidate_the_cache() {
        let root = fixture();
        std::fs::create_dir_all(root.path().join("node_modules")).unwrap();
        let expected = fingerprint(root.path());
        record_cache(root.path(), &expected).unwrap();

        let newer_node =
            dependency_fingerprint(root.path(), "v24.0.0".into(), "10.9.8".into()).unwrap();
        let newer_npm =
            dependency_fingerprint(root.path(), "v22.23.2".into(), "11.0.0".into()).unwrap();
        assert!(!cache_matches(root.path(), &newer_node));
        assert!(!cache_matches(root.path(), &newer_npm));
    }

    #[test]
    fn failed_install_cannot_leave_a_trusted_marker() {
        let root = fixture();
        std::fs::create_dir_all(root.path().join("node_modules")).unwrap();
        let expected = fingerprint(root.path());
        record_cache(root.path(), &expected).unwrap();
        let mut install = |_: &mut dyn FnMut(&str)| Err("network unavailable".to_string());

        let result = install_dependencies(root.path(), &expected, &mut |_| {}, &mut install);
        assert!(result.is_err());
        assert!(!cache_marker(root.path()).exists());
        assert!(!cache_matches(root.path(), &expected));
    }

    #[test]
    fn missing_or_corrupt_markers_are_cache_misses() {
        let root = fixture();
        std::fs::create_dir_all(root.path().join("node_modules")).unwrap();
        let expected = fingerprint(root.path());
        assert!(!cache_matches(root.path(), &expected));
        std::fs::write(cache_marker(root.path()), "not json").unwrap();
        assert!(!cache_matches(root.path(), &expected));
    }

    #[test]
    fn a_cached_build_failure_repairs_dependencies_and_retries_once() {
        let root = fixture();
        std::fs::create_dir_all(root.path().join("node_modules")).unwrap();
        let expected = fingerprint(root.path());
        record_cache(root.path(), &expected).unwrap();
        let mut installs = 0;
        let mut builds = 0;
        let mut install = |_: &mut dyn FnMut(&str)| {
            installs += 1;
            Ok(())
        };
        let mut build = |_: &mut dyn FnMut(&str)| {
            builds += 1;
            if builds == 1 {
                Err("cached module is corrupt".to_string())
            } else {
                Ok(())
            }
        };

        prepare_with_commands(
            root.path(),
            &expected,
            &mut |_| {},
            &mut install,
            &mut build,
        )
        .unwrap();

        assert_eq!(installs, 1);
        assert_eq!(builds, 2);
        assert!(cache_matches(root.path(), &expected));
    }
}

#[cfg(test)]
pub mod fake {
    use super::*;
    use std::sync::Arc;

    /// A controllable fake build runner for tests.
    #[derive(Clone)]
    pub struct FakeBuildRunner {
        inner: Arc<std::sync::Mutex<FakeState>>,
    }

    struct FakeState {
        /// Whether `prepare` should fail.
        fail: bool,
        /// Records every stage the runner was asked to perform.
        calls: Vec<String>,
    }

    impl FakeBuildRunner {
        pub fn new() -> Self {
            FakeBuildRunner {
                inner: Arc::new(std::sync::Mutex::new(FakeState {
                    fail: false,
                    calls: Vec::new(),
                })),
            }
        }

        pub fn failing(self) -> Self {
            self.inner.lock().unwrap().fail = true;
            self
        }

        pub fn calls(&self) -> Vec<String> {
            self.inner.lock().unwrap().calls.clone()
        }
    }

    impl BuildRunner for FakeBuildRunner {
        fn prepare(&mut self, root: &Path, progress: &mut dyn FnMut(&str)) -> Result<(), String> {
            self.inner.lock().unwrap().calls.push("prepare".to_string());
            // Leave a visible trace so tests can assert a build ran in the
            // right directory.
            progress("fake build");
            let state = self.inner.lock().unwrap();
            if state.fail {
                return Err("simulated build failure".to_string());
            }
            std::fs::create_dir_all(root.join("apps/desktop/out/main")).unwrap();
            std::fs::write(root.join("apps/desktop/out/main/index.js"), "// built").unwrap();
            Ok(())
        }
    }
}
