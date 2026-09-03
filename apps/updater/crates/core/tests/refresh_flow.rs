//! End-to-end update flows against a real `git` remote, with a fake build
//! runner. These prove the rollback and safety guarantees the update handoff
//! depends on.

mod common;

use common::{FakeBuilder, git_in, init_repos};
use marvi_bootstrap_core::{Channel, UpdateConfig, check, run_update};

fn config(local: &std::path::Path, state: &std::path::Path, builder: FakeBuilder) -> UpdateConfig {
    UpdateConfig {
        install_root: local.to_path_buf(),
        channel: Channel::Nightly,
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
fn up_to_date_nightly_install_checks_the_latest_release_for_its_updater() {
    let repos = init_repos();
    let state = repos._tmp.path().join("state");
    repos.tag("v0.6.0");
    let mut lines = Vec::new();

    let mut cfg = config(&repos.local, &state, FakeBuilder::ok());
    let out = run_update(&mut cfg, &mut |line| lines.push(line.to_string()));

    assert_eq!(out.status, "ok");
    assert_eq!(out.message, "Already up to date.");
    assert!(
        lines
            .iter()
            .any(|line| line == "checking updater release v0.6.0"),
        "progress: {lines:?}"
    );
    assert!(
        lines
            .iter()
            .all(|line| !line.contains("release origin/main")),
        "progress: {lines:?}"
    );
}

#[test]
fn nightly_update_fast_forwards_and_builds() {
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
fn nightly_check_returns_the_commits_that_will_be_installed() {
    let repos = init_repos();
    repos.commit(
        "feature.txt",
        "ready",
        "feat(updater): show available changes",
    );

    let out = check(&repos.local, Channel::Nightly);

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
fn local_changes_are_set_aside_and_the_update_goes_on() {
    // The dead end this replaces: status "skipped", message "Local changes
    // present; update skipped to avoid discarding them", and no way out from
    // inside the app. The window said "close and try again"; trying again did
    // the same thing forever. The changes have to survive -- but blocking
    // every future update is not how.
    let repos = init_repos();
    let state = repos._tmp.path().join("state");
    let before = repos.head(&repos.local);
    std::fs::write(repos.local.join("f.txt"), "local edit").unwrap();
    let new_head = repos.commit("g.txt", "2", "c2");

    let mut cfg = config(&repos.local, &state, FakeBuilder::ok());
    let out = run_update(&mut cfg, &mut |_| {});

    assert_eq!(out.status, "ok", "message: {}", out.message);
    assert_ne!(
        repos.head(&repos.local),
        before,
        "the update did not happen"
    );
    assert_eq!(repos.head(&repos.local), new_head);

    // Set aside, not thrown away: the message names the file and prints the
    // one command that puts it back.
    assert!(out.message.contains("f.txt"), "message: {}", out.message);
    assert!(
        out.message.contains("git stash apply"),
        "message: {}",
        out.message
    );

    // And the edit is really recoverable, not merely described as such.
    let stashed = git_in(&repos.local, &["stash", "list"]);
    assert!(stashed.contains("marvi-updater"), "stash list: {stashed}");
    git_in(&repos.local, &["stash", "apply", "stash@{0}"]);
    assert_eq!(
        std::fs::read_to_string(repos.local.join("f.txt")).unwrap(),
        "local edit"
    );
}

#[test]
fn an_untracked_file_is_set_aside_too() {
    // The shape this actually takes: a file copied into the install to test
    // something. `git stash` without --include-untracked leaves it behind,
    // the tree stays dirty, and the update fails on the next run instead.
    let repos = init_repos();
    let state = repos._tmp.path().join("state");
    std::fs::write(repos.local.join("stray.txt"), "copied in by hand").unwrap();
    repos.commit("g.txt", "2", "c2");

    let mut cfg = config(&repos.local, &state, FakeBuilder::ok());
    let out = run_update(&mut cfg, &mut |_| {});

    assert_eq!(out.status, "ok", "message: {}", out.message);
    assert!(!repos.local.join("stray.txt").exists(), "still in the way");
    git_in(&repos.local, &["stash", "apply", "stash@{0}"]);
    assert!(repos.local.join("stray.txt").exists(), "not recoverable");
}

#[test]
fn a_clean_tree_says_nothing_about_stashes() {
    // The common case must not grow a paragraph about git.
    let repos = init_repos();
    let state = repos._tmp.path().join("state");
    repos.commit("g.txt", "2", "c2");

    let mut cfg = config(&repos.local, &state, FakeBuilder::ok());
    let out = run_update(&mut cfg, &mut |_| {});

    assert_eq!(out.status, "ok", "message: {}", out.message);
    assert_eq!(out.message, "Updated successfully.");
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
