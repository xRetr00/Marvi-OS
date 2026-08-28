//! End-to-end update flows against a real `git` remote, with a fake build
//! runner. These prove the rollback and safety guarantees the update handoff
//! depends on.

mod common;

use common::{init_repos, FakeBuilder};
use marvi_bootstrap_core::{check, run_update, Channel, UpdateConfig};

fn config(local: &std::path::Path, state: &std::path::Path, builder: FakeBuilder) -> UpdateConfig {
    UpdateConfig {
        install_root: local.to_path_buf(),
        channel: Channel::Dev,
        state_dir: state.to_path_buf(),
        desktop_pid: None,
        relaunch_exe: None,
        no_relaunch: true,
        builder: Box::new(builder),
        provision_toolchain: false,
    }
}

#[test]
fn up_to_date_reports_ok_without_moving() {
    let repos = init_repos();
    let state = repos._tmp.path().join("state");
    let before = repos.head(&repos.local);

    let mut cfg = config(&repos.local, &state, FakeBuilder::ok());
    let out = run_update(&mut cfg, &mut |_| {});

    assert_eq!(out.status, "ok");
    assert_eq!(out.message, "Already up to date.");
    assert_eq!(repos.head(&repos.local), before);
}

#[test]
fn dev_update_fast_forwards_and_builds() {
    let repos = init_repos();
    let state = repos._tmp.path().join("state");
    let old = repos.head(&repos.local);
    let new = repos.commit("f.txt", "2", "c2");

    let mut cfg = config(&repos.local, &state, FakeBuilder::ok());
    let out = run_update(&mut cfg, &mut |_| {});

    assert_eq!(out.status, "ok");
    assert_eq!(out.from.as_deref(), Some(old.as_str()));
    assert_eq!(out.to.as_deref(), Some(new.as_str()));
    assert_eq!(repos.head(&repos.local), new);
    assert!(repos.local.join("apps/desktop/out/main/index.js").is_file());
}

#[test]
fn dev_check_returns_the_commits_that_will_be_installed() {
    let repos = init_repos();
    repos.commit(
        "feature.txt",
        "ready",
        "feat(updater): show available changes",
    );

    let out = check(&repos.local, Channel::Dev);

    assert!(out.available);
    assert_eq!(out.behind_by, 1);
    assert_eq!(out.commits.len(), 1);
    assert_eq!(
        out.commits[0].summary,
        "feat(updater): show available changes"
    );
}

#[test]
fn failed_build_restores_the_previous_commit() {
    let repos = init_repos();
    let state = repos._tmp.path().join("state");
    let old = repos.head(&repos.local);
    repos.commit("f.txt", "2", "c2");

    let mut cfg = config(&repos.local, &state, FakeBuilder::failing());
    let out = run_update(&mut cfg, &mut |_| {});

    assert_eq!(out.status, "failed");
    assert!(
        out.message.contains("previous version was restored"),
        "message: {}",
        out.message
    );
    // The checkout was rolled back to the working commit.
    assert_eq!(repos.head(&repos.local), old);
}

#[test]
fn dirty_tree_is_skipped_without_touching_the_checkout() {
    let repos = init_repos();
    let state = repos._tmp.path().join("state");
    let before = repos.head(&repos.local);
    std::fs::write(repos.local.join("f.txt"), "local edit").unwrap();

    let mut cfg = config(&repos.local, &state, FakeBuilder::ok());
    let out = run_update(&mut cfg, &mut |_| {});

    assert_eq!(out.status, "skipped");
    assert!(out.message.contains("Local changes"));
    assert_eq!(repos.head(&repos.local), before);
}

#[test]
fn release_channel_checks_out_the_latest_tag() {
    let repos = init_repos();
    let state = repos._tmp.path().join("state");
    let old = repos.head(&repos.local);
    repos.tag("v1.0.0");
    let new = repos.commit("f.txt", "2", "c2");
    repos.tag("v1.1.0");

    let mut cfg = UpdateConfig {
        channel: Channel::Release,
        ..config(&repos.local, &state, FakeBuilder::ok())
    };
    let out = run_update(&mut cfg, &mut |_| {});

    assert_eq!(out.status, "ok");
    assert_eq!(out.target_ref.as_deref(), Some("v1.1.0"));
    assert_eq!(out.from.as_deref(), Some(old.as_str()));
    assert_eq!(out.to.as_deref(), Some(new.as_str()));
    assert_eq!(repos.head(&repos.local), new);
}

#[test]
fn release_channel_is_up_to_date_when_on_the_latest_tag() {
    let repos = init_repos();
    let state = repos._tmp.path().join("state");
    repos.tag("v1.0.0");
    // Clone again at the tag so the local checkout IS the latest release.
    let local_at_tag = repos._tmp.path().join("local-tag");
    let status = std::process::Command::new("git")
        .args([
            "clone",
            "--branch",
            "v1.0.0",
            repos.remote.to_str().unwrap(),
            local_at_tag.to_str().unwrap(),
        ])
        .current_dir(repos._tmp.path())
        .output()
        .unwrap()
        .status;
    assert!(status.success());

    let mut cfg = UpdateConfig {
        install_root: local_at_tag,
        channel: Channel::Release,
        ..config(&repos.local, &state, FakeBuilder::ok())
    };
    let out = run_update(&mut cfg, &mut |_| {});
    assert_eq!(out.status, "ok");
    assert_eq!(out.message, "Already up to date.");
}
