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
        provision_toolchain: false,
        use_gpu: None,
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

#[test]
fn running_the_installer_over_an_existing_checkout_repairs_it() {
    // It used to fail with "use update instead", which is useless advice when
    // the reason you reached for the installer is that updating from inside the
    // app does not work. The only way out was to uninstall first.
    let repos = init_repos();
    repos.tag("v1.0.0");
    let state = repos._tmp.path().join("state");
    let dest = repos._tmp.path().join("installed");

    // The real repository ignores build output, so a built checkout is clean
    // and the update's dirty-tree guard does not fire. The fixture has to say
    // so too, or this tests the fixture rather than the repair.
    repos.commit(".gitignore", "apps/desktop/out/
", "ignore build output");
    repos.tag("v1.0.1");

    let mut first = install_cfg(&dest, &repos.remote, &state, FakeBuilder::ok());
    assert_eq!(install(&mut first, &mut |_| {}).status, "ok");

    // Second run over the same directory: a repair, not a refusal.
    let mut again = install_cfg(&dest, &repos.remote, &state, FakeBuilder::ok());
    let out = install(&mut again, &mut |_| {});

    assert_eq!(out.status, "ok", "message: {}", out.message);
    assert!(dest.join(".git").is_dir(), "the checkout survived the repair");
}

#[test]
fn repairing_replaces_the_installed_updater() {
    // The reported bug. The repair path returned before the copy a fresh
    // install does, so running a newly downloaded installer left the *old*
    // bootstrap in state/bin -- and the updater is the one component that
    // cannot be fixed by updating, because it is what performs the update.
    let repos = init_repos();
    repos.tag("v1.0.0");
    let state = repos._tmp.path().join("state");
    let dest = repos._tmp.path().join("installed");
    repos.commit(".gitignore", "apps/desktop/out/
", "ignore build output");
    repos.tag("v1.0.1");

    let mut first = install_cfg(&dest, &repos.remote, &state, FakeBuilder::ok());
    assert_eq!(install(&mut first, &mut |_| {}).status, "ok");

    // Stand in for an older bootstrap sitting where the app looks for it.
    let installed = state.join("bin").join("marvi-bootstrap.exe");
    assert!(installed.is_file(), "the first install placed a bootstrap");
    std::fs::write(&installed, b"an older updater").unwrap();

    let mut again = install_cfg(&dest, &repos.remote, &state, FakeBuilder::ok());
    assert_eq!(install(&mut again, &mut |_| {}).status, "ok");

    assert_ne!(
        std::fs::read(&installed).unwrap(),
        b"an older updater",
        "repair left the old updater in place"
    );
}

#[test]
fn a_non_empty_directory_that_is_not_a_checkout_is_still_refused() {
    // Repair applies to Marvi's own checkout. Someone else's files are not
    // Marvi's to rebuild.
    let repos = init_repos();
    repos.tag("v1.0.0");
    let state = repos._tmp.path().join("state");
    let dest = repos._tmp.path().join("someone-elses-folder");
    std::fs::create_dir_all(&dest).unwrap();
    std::fs::write(dest.join("keep.txt"), "do not delete").unwrap();

    let mut cfg = install_cfg(&dest, &repos.remote, &state, FakeBuilder::ok());
    let out = install(&mut cfg, &mut |_| {});

    assert_eq!(out.status, "failed");
    assert!(dest.join("keep.txt").is_file());
}
