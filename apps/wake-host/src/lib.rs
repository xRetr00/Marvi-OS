//! The wake word pipeline, as a library so the binary and the tests share it.
//!
//! Split out for one reason: the parity test needs to call the detector
//! directly. A test that could only drive the executable would be testing
//! argument parsing as much as inference, and the thing worth guarding here is
//! the arithmetic.

pub mod detector;
