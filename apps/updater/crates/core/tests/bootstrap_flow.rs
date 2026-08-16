//! Installer flow: clone + build + atomic swap, and its failure modes.

mod common;

use common::{FakeBuilder, init_repos};
use marvi_bootstrap_core::{Channel, InstallConfig, install};

fn install_cfg(
    install_root: &std::path::Path,
    repo: &std::path::Path,
    state: &std::path::Path,
    builder: FakeBuilder,
) -> InstallConfig {
    InstallConfig {
        install_root: install_root.to_path_buf(),
        channel: Channel::Release,
        repo: repo.to_string_lossy().to_string(),
        state_dir: state.to_path_buf(),
        relaunch_exe: None,
        builder: Box::new(builder),
    }
}

#[test]
fn installs_a_release_into_a_fresh_directory() {
    let repos = init_repos();
    repos.tag("v1.0.0");
    let state = repos._tmp.path().join("state");
    let dest = repos._tmp.path().join("installed");

    let mut cfg = install_cfg(&dest, &repos.remote, &state, FakeBuilder::ok());
    let out = install(&mut cfg, &mut |_| {});

    assert_eq!(out.status, "ok", "message: {}", out.message);
    assert!(dest.join(".git").is_dir());
    assert!(dest.join("apps/desktop/out/main/index.js").is_file());
    assert_eq!(out.to.as_deref(), Some(repos.head(&repos.remote).as_str()));
}

#[test]
fn refuses_to_overwrite_a_non_empty_directory() {
    let repos = init_repos();
    repos.tag("v1.0.0");
    let state = repos._tmp.path().join("state");
    let dest = repos._tmp.path().join("occupied");
    std::fs::create_dir_all(&dest).unwrap();
    std::fs::write(dest.join("keep.txt"), "do not delete").unwrap();

    let mut cfg = install_cfg(&dest, &repos.remote, &state, FakeBuilder::ok());
    let out = install(&mut cfg, &mut |_| {});

    assert_eq!(out.status, "failed");
    assert!(dest.join("keep.txt").is_file(), "existing data was touched");
    assert!(!dest.join(".git").exists());
}

#[test]
fn dev_install_clones_main() {
    let repos = init_repos();
    let state = repos._tmp.path().join("state");
    let dest = repos._tmp.path().join("dev-install");

    let mut cfg = InstallConfig {
        channel: Channel::Dev,
        ..install_cfg(&dest, &repos.remote, &state, FakeBuilder::ok())
    };
    let out = install(&mut cfg, &mut |_| {});

    assert_eq!(out.status, "ok", "message: {}", out.message);
    assert!(dest.join(".git").is_dir());
}
