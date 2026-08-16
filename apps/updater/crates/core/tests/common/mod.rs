//! Shared helpers for the core integration tests: a real local "remote" repo
//! and a fake build runner that stands in for `npm`.
#![allow(dead_code)]

use std::fs;
use std::path::{Path, PathBuf};

use marvi_bootstrap_core::BuildRunner;
use tempfile::TempDir;

pub struct TestRepos {
    pub _tmp: TempDir,
    pub remote: PathBuf,
    pub local: PathBuf,
}

fn git(dir: &Path, args: &[&str]) -> String {
    let out = std::process::Command::new("git")
        .args(args)
        .current_dir(dir)
        .output()
        .unwrap_or_else(|e| panic!("spawn git {args:?}: {e}"));
    assert!(
        out.status.success(),
        "git {args:?} failed: {}",
        String::from_utf8_lossy(&out.stderr)
    );
    String::from_utf8_lossy(&out.stdout).trim().to_string()
}

/// Create a remote repo with one commit, and a fresh clone of it.
pub fn init_repos() -> TestRepos {
    let tmp = TempDir::new().unwrap();
    let remote = tmp.path().join("remote");
    fs::create_dir(&remote).unwrap();
    git(&remote, &["init", "-b", "main"]);
    git(&remote, &["config", "user.email", "test@example.com"]);
    git(&remote, &["config", "user.name", "Test"]);
    fs::write(remote.join("f.txt"), "1").unwrap();
    git(&remote, &["add", "f.txt"]);
    git(&remote, &["commit", "-m", "c1"]);

    let local = tmp.path().join("local");
    git(
        tmp.path(),
        &["clone", remote.to_str().unwrap(), local.to_str().unwrap()],
    );

    TestRepos {
        _tmp: tmp,
        remote,
        local,
    }
}

impl TestRepos {
    /// Add a commit to the remote and return its SHA.
    pub fn commit(&self, file: &str, content: &str, msg: &str) -> String {
        fs::write(self.remote.join(file), content).unwrap();
        git(&self.remote, &["add", "."]);
        git(&self.remote, &["commit", "-m", msg]);
        git(&self.remote, &["rev-parse", "HEAD"])
    }

    pub fn tag(&self, name: &str) {
        // Annotated tag, matching `scripts/release.ps1` (`git tag -a`).
        git(&self.remote, &["tag", "-a", name, "-m", &format!("release {name}")]);
    }

    pub fn head(&self, dir: &Path) -> String {
        git(dir, &["rev-parse", "HEAD"])
    }
}

/// Fake build runner: records that it ran and (unless failing) produces the
/// smoke-test artifact so the update/install logic considers the build good.
pub struct FakeBuilder {
    pub fail: bool,
    pub calls: usize,
}

impl FakeBuilder {
    pub fn ok() -> Self {
        FakeBuilder { fail: false, calls: 0 }
    }
    pub fn failing() -> Self {
        FakeBuilder { fail: true, calls: 0 }
    }
}

impl BuildRunner for FakeBuilder {
    fn prepare(&mut self, root: &Path, _progress: &mut dyn FnMut(&str)) -> Result<(), String> {
        self.calls += 1;
        if self.fail {
            return Err("simulated build failure".to_string());
        }
        let out = root.join("apps/desktop/out/main");
        fs::create_dir_all(&out).unwrap();
        fs::write(out.join("index.js"), "// built").unwrap();
        Ok(())
    }
}
