//! Whether to bring the listener thread back after it ends on its own.
//!
//! This is the arithmetic behind the fix for the bug the whole rewrite was
//! meant to close: a wake word that stops and nobody notices. `listen` runs on
//! its own thread so the tray's message pump keeps the icon alive either way,
//! and that used to be the whole story -- if the thread ended (an inference
//! error that still found a way past every `?`, a panic inside the ONNX
//! runtime's own C++ that Rust cannot catch), the tray sat there with a dead
//! microphone and a tooltip that still said "listening for her name". Nothing
//! watched the thread, so nothing restarted it, and `wake.json` went on
//! claiming `running: true` with a heartbeat that had stopped moving hours
//! earlier.
//!
//! The tray now restarts the thread when it ends early. This is the decision
//! of whether that is a good idea *this time* -- separated from the actual
//! spawning, which needs a live Win32 message loop and a real microphone, so
//! neither is available to a test. The policy itself is pure arithmetic and
//! does not need either.

use std::time::Duration;

/// A restart within this long of the previous start counts as "fast" --
/// evidence the thing that killed it is still there, not a one-off.
const FAST: Duration = Duration::from_secs(2);

/// Fast restarts in a row before giving up. Enough to ride out a transient
/// hiccup (a WASAPI device in the middle of being unplugged, one bad ONNX
/// allocation), not so many that a genuinely broken install spins the CPU
/// relaunching a thread that will only die again.
const GIVE_UP_AFTER: u32 = 3;

/// Tracks consecutive fast failures and decides whether the next one is worth
/// trying again for.
#[derive(Default)]
pub struct Backoff {
    fast_failures: u32,
}

impl Backoff {
    pub fn new() -> Self {
        Self::default()
    }

    /// Call once when the worker thread has just ended, with how long it had
    /// been running. Returns whether to start it again.
    ///
    /// A run that lasted a while resets the count -- it was doing its job for
    /// a real stretch of time, so whatever ended it is treated as new trouble,
    /// not a continuation of the last one.
    pub fn should_restart(&mut self, ran_for: Duration) -> bool {
        if ran_for < FAST {
            self.fast_failures += 1;
        } else {
            self.fast_failures = 0;
        }
        self.fast_failures < GIVE_UP_AFTER
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_single_fast_failure_is_worth_retrying() {
        let mut backoff = Backoff::new();
        assert!(backoff.should_restart(Duration::from_millis(50)));
    }

    #[test]
    fn three_fast_failures_in_a_row_give_up() {
        let mut backoff = Backoff::new();
        assert!(backoff.should_restart(Duration::from_millis(50)));
        assert!(backoff.should_restart(Duration::from_millis(50)));
        // The third is the one that trips it: two retries already granted,
        // and a third failure this fast says the next attempt will not fare
        // any better.
        assert!(!backoff.should_restart(Duration::from_millis(50)));
    }

    #[test]
    fn a_long_run_resets_the_count() {
        let mut backoff = Backoff::new();
        assert!(backoff.should_restart(Duration::from_millis(50)));
        assert!(backoff.should_restart(Duration::from_millis(50)));
        // Ran fine for a while before this failure -- back to a clean slate,
        // not one strike away from giving up.
        assert!(backoff.should_restart(Duration::from_secs(30)));
        assert!(backoff.should_restart(Duration::from_millis(50)));
        assert!(backoff.should_restart(Duration::from_millis(50)));
    }

    #[test]
    fn giving_up_is_not_forever_reported() {
        // Once tripped, it stays tripped until a run lasts long enough to
        // prove things are working again -- it must not silently start
        // retrying on the very next fast failure.
        let mut backoff = Backoff::new();
        for _ in 0..GIVE_UP_AFTER {
            backoff.should_restart(Duration::from_millis(10));
        }
        assert!(!backoff.should_restart(Duration::from_millis(10)));
    }
}
