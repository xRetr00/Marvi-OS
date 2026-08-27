//! Whether the new listener stops the old one, and whether it stops anything
//! else. The second question is the one worth testing: `predecessor()` names a
//! process id that gets terminated, so every path that returns `Some` on a
//! stale or absent file is a path that kills something at random.

use std::sync::Mutex;

use marvi_wake_host::state::{self, State};
use marvi_wake_host::takeover;

/// `MARVI_HOME` is process-wide and these all set it.
static ONE_AT_A_TIME: Mutex<()> = Mutex::new(());

fn with_state(body: impl FnOnce()) {
    let _guard = ONE_AT_A_TIME.lock().unwrap_or_else(|poisoned| poisoned.into_inner());
    let home = std::env::temp_dir().join(format!("marvi-takeover-{}", std::process::id()));
    let _ = std::fs::remove_dir_all(&home);
    unsafe { std::env::set_var("MARVI_HOME", &home) };
    body();
    let _ = std::fs::remove_dir_all(&home);
}

#[test]
fn no_file_means_nobody_was_listening() {
    with_state(|| assert_eq!(takeover::predecessor(), None));
}

#[test]
fn a_live_listener_is_the_one_to_stop() {
    with_state(|| {
        State { pid: 4242, running: true, heartbeat: state::now(), ..Default::default() }.write();
        assert_eq!(takeover::predecessor(), Some(4242));
    });
}

#[test]
fn a_stale_file_names_a_pid_windows_has_since_reused() {
    // The listener exited without clearing it. Terminating that number now is
    // terminating whatever inherited it, which could be anything.
    with_state(|| {
        State {
            pid: 4242,
            running: true,
            heartbeat: state::now() - takeover::STALE - 1.0,
            ..Default::default()
        }
        .write();
        assert_eq!(takeover::predecessor(), None);
    });
}

#[test]
fn a_listener_that_said_it_stopped_is_not_stopped_again() {
    with_state(|| {
        State { pid: 4242, running: false, heartbeat: state::now(), ..Default::default() }.write();
        assert_eq!(takeover::predecessor(), None);
    });
}

#[test]
fn it_does_not_stop_itself() {
    // The same process rewriting its own state file, on a restart of the
    // listen thread, must not read it as a predecessor.
    with_state(|| {
        State {
            pid: std::process::id(),
            running: true,
            heartbeat: state::now(),
            ..Default::default()
        }
        .write();
        assert_eq!(takeover::predecessor(), None);
    });
}

#[test]
fn nonsense_in_the_file_is_nobody() {
    with_state(|| {
        let path = state::path();
        std::fs::create_dir_all(path.parent().unwrap()).unwrap();
        std::fs::write(&path, "half a wri").unwrap();
        assert_eq!(takeover::predecessor(), None);
    });
}
