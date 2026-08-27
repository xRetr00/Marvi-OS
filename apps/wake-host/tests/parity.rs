//! The three-stage pipeline, pinned against the implementation it was ported from.
//!
//! `livekit.wakeword` ran mel → embedding → classifier for the Python daemon,
//! so the daemon never had to know the shapes, the strides, or that int16 has
//! to be divided by 32768 before the mel model sees it. Standing alone means
//! owning all of that, and the first draft of the port got the normalisation
//! wrong — which does not crash, does not log, and produces a wake word that
//! simply never fires.
//!
//! There is no way to catch that by saying "Marvi" at it, because the answer
//! when it is broken and the answer before you have spoken are the same. So
//! both implementations were fed the same bytes and their scores compared.
//! These are the numbers Python produced, to six decimal places:
//!
//! ```text
//! warming  warming  warming  0.003756  0.005808  0.003965  0.003031  0.002456
//! ```
//!
//! The fixture is four seconds of deterministic noise rather than speech. It
//! does not need to be a wake word: what is under test is whether two
//! pipelines agree, and agreeing on an arbitrary signal is the stronger claim.

use std::path::Path;

use marvi_wake_host::detector::{Detector, HOP_SAMPLES};

/// From `livekit.wakeword`, on `tests/fixtures/parity.raw`.
const EXPECTED: [f32; 5] = [0.003_756, 0.005_808, 0.003_965, 0.003_031, 0.002_456];

/// Six decimal places, which is what the comparison was made at. Looser would
/// not notice a pipeline that is subtly wrong; tighter would fail on the last
/// bit of a float that took a different route through two runtimes.
const TOLERANCE: f32 = 1e-6;

#[test]
fn the_port_scores_what_the_python_pipeline_scores() {
    let fixture = Path::new(env!("CARGO_MANIFEST_DIR")).join("tests/fixtures/parity.raw");
    let raw = std::fs::read(&fixture).expect("the fixture is committed beside this test");
    let samples: Vec<i16> = raw
        .chunks_exact(2)
        .map(|pair| i16::from_le_bytes([pair[0], pair[1]]))
        .collect();

    let models = Path::new(env!("CARGO_MANIFEST_DIR")).join("models");
    let mut detector = Detector::load(&models).expect("the three models are committed");

    let mut scored = Vec::new();
    let mut warming = 0;
    for hop in samples.chunks(HOP_SAMPLES) {
        match detector.push(hop).expect("inference runs") {
            Some(score) => scored.push(score),
            // Not "heard nothing" — "cannot say yet". Two seconds of audio are
            // needed before there is a window to judge.
            None => warming += 1,
        }
    }

    assert_eq!(warming, 3, "a 2s window fills after three 0.5s hops");
    assert_eq!(scored.len(), EXPECTED.len());
    for (got, want) in scored.iter().zip(EXPECTED) {
        assert!(
            (got - want).abs() < TOLERANCE,
            "scored {got:.6}, python scored {want:.6}"
        );
    }
}
