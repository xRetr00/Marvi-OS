//! Marvi's wake word, as a program rather than a Python process.
//!
//! It had been `pythonw.exe -m marvi_agent.wake_daemon`: a windowless
//! interpreter, started by the desktop, holding a microphone open all day. That
//! shape produced most of this feature's bugs — it died without anybody
//! noticing, it could not be seen or stopped, and "is it running?" was answered
//! by reading a heartbeat file and guessing.
//!
//! So: one executable, one job. A tray icon that says whether it is listening
//! and lets you quit it, an autostart entry it owns itself, and the same state
//! file the Gateway already reads. The pet host is the precedent — a small
//! native thing that does one thing where Electron was the wrong tool.
//!
//! ## Modes
//!
//! `--score <file>` reads raw 16-bit mono PCM and prints one score per hop.
//! That exists for the test that matters: the three-stage pipeline was ported
//! by hand from `livekit.wakeword`, and the way to know a port is faithful is
//! to feed both the same audio and compare. Without it the only test is to say
//! "Marvi" and see, which proves nothing when the answer is no.

use std::path::{Path, PathBuf};

use marvi_wake_host::detector::{Detector, HOP_SAMPLES};

fn models_dir() -> PathBuf {
    // Beside the executable when installed, in the crate while developing.
    // Same resolution the pet host uses, for the same reason: one binary that
    // runs from either place without a launcher deciding for it.
    let beside = std::env::current_exe()
        .ok()
        .and_then(|exe| exe.parent().map(|dir| dir.join("models")));
    match beside {
        Some(path) if path.join("marvi.onnx").is_file() => path,
        _ => Path::new(env!("CARGO_MANIFEST_DIR")).join("models"),
    }
}

/// Score a raw PCM file, one line per hop. For the parity test.
fn score_file(path: &str) -> Result<(), Box<dyn std::error::Error>> {
    let raw = std::fs::read(path)?;
    let samples: Vec<i16> = raw
        .chunks_exact(2)
        .map(|pair| i16::from_le_bytes([pair[0], pair[1]]))
        .collect();

    let mut detector = Detector::load(&models_dir())?;
    for hop in samples.chunks(HOP_SAMPLES) {
        match detector.push(hop)? {
            Some(score) => println!("{score:.6}"),
            None => println!("warming"),
        }
    }
    Ok(())
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let arguments: Vec<String> = std::env::args().collect();
    if let Some(index) = arguments.iter().position(|a| a == "--score") {
        let path = arguments.get(index + 1).ok_or("--score needs a file")?;
        return score_file(path);
    }
    eprintln!("marvi-wake-host: only --score <raw pcm> is implemented so far");
    Ok(())
}
