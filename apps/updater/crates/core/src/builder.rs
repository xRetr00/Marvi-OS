//! Build steps, abstracted behind a trait so the update/install logic can be
//! tested against a fake without running a real `npm` build.

use std::path::Path;
use std::time::Duration;

use crate::util::run_shell_reporting;

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
        progress("installing dependencies (npm ci)");
        run_shell_reporting("npm ci", root, self.ci_timeout, progress)
            .map_err(|e| format!("dependency installation failed: {e}"))?;

        progress("building (npm run build:unpack)");
        run_shell_reporting("npm run build:unpack", root, self.build_timeout, progress)
            .map_err(|e| format!("build failed: {e}"))?;

        Ok(())
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
