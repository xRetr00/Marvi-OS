//! The wake word listener, as a library so the binary and the tests share it.
//!
//! Split out for one reason: the parity test needs to call the detector
//! directly. A test that could only drive the executable would be testing
//! argument parsing as much as inference, and the arithmetic is what is worth
//! guarding here.

pub mod audio;
pub mod autostart;
pub mod detector;
pub mod settings;
pub mod state;
pub mod takeover;
