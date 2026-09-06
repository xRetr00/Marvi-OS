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

/// Maximum delay between attempts. A microphone can be absent for hours and
/// return later; giving up permanently turns a recoverable device change into
/// a listener that stays dead until the next login.
const MAX_DELAY: Duration = Duration::from_secs(30);

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
    /// been running. Returns how long to wait before starting it again.
    ///
    /// A run that lasted a while resets the count -- it was doing its job for
    /// a real stretch of time, so whatever ended it is treated as new trouble,
    /// not a continuation of the last one.
    pub fn delay(&mut self, ran_for: Duration) -> Duration {
        if ran_for < FAST {
            self.fast_failures = self.fast_failures.saturating_add(1);
        } else {
            self.fast_failures = 0;
        }
        if self.fast_failures == 0 {
            return Duration::ZERO;
        }
        let seconds = 1u64
            .checked_shl(self.fast_failures.saturating_sub(1).min(5))
            .unwrap_or(MAX_DELAY.as_secs())
            .min(MAX_DELAY.as_secs());
        Duration::from_secs(seconds)
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn a_single_fast_failure_is_worth_retrying() {
        let mut backoff = Backoff::new();
        assert_eq!(backoff.delay(Duration::from_millis(50)), Duration::from_secs(1));
    }

    #[test]
    fn repeated_fast_failures_back_off_without_giving_up() {
        let mut backoff = Backoff::new();
        assert_eq!(backoff.delay(Duration::from_millis(50)), Duration::from_secs(1));
        assert_eq!(backoff.delay(Duration::from_millis(50)), Duration::from_secs(2));
        assert_eq!(backoff.delay(Duration::from_millis(50)), Duration::from_secs(4));
        for _ in 0..20 {
            assert!(backoff.delay(Duration::from_millis(50)) <= MAX_DELAY);
        }
    }

    #[test]
    fn a_long_run_resets_the_count() {
        let mut backoff = Backoff::new();
        assert_eq!(backoff.delay(Duration::from_millis(50)), Duration::from_secs(1));
        assert_eq!(backoff.delay(Duration::from_millis(50)), Duration::from_secs(2));
        // Ran fine for a while before this failure -- back to a clean slate,
        // not one strike away from giving up.
        assert_eq!(backoff.delay(Duration::from_secs(30)), Duration::ZERO);
        assert_eq!(backoff.delay(Duration::from_millis(50)), Duration::from_secs(1));
        assert_eq!(backoff.delay(Duration::from_millis(50)), Duration::from_secs(2));
    }
}
