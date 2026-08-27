//! Hearing "Marvi", in three stages.
//!
//! The wake model is not fed audio. It takes sixteen 96-dimensional embeddings
//! and returns one score, so two models run in front of it:
//!
//! 1. `melspectrogram.onnx` — samples to mel frames, 32 bins each, then the
//!    `x / 10 + 2` rescale openWakeWord bakes into its frontend rather than
//!    into the graph.
//! 2. `embedding_model.onnx` — a 76-frame window, stride 8, to one 96-value
//!    embedding.
//! 3. `marvi.onnx` — the last 16 embeddings to a score in 0..1.
//!
//! `livekit.wakeword` ran this for the Python daemon, so the daemon never had
//! to know it. Standing alone means owning it, and every constant here was read
//! out of that implementation rather than guessed — including the `/ 32768`
//! that turns int16 into the range the mel model expects, which was missing
//! from the first draft of this file and would have produced a wake word that
//! silently never fired.
//!
//! ## Why the whole window is rescored each hop
//!
//! Rolling the three stages incrementally would be cheaper and is what the
//! shapes invite. It would also be wrong: the mel model is a windowed
//! transform, so frames computed from a 0.5s hop in isolation do not equal the
//! frames the same audio produces inside a 2s window. The edges differ, and the
//! edges are where a wake word usually sits.
//!
//! So this does what the daemon did: keep two seconds of audio, and on every
//! hop run the lot. It is a port, not a redesign — the version that is known to
//! detect the word is the one worth having, and 2s of 16kHz mono through three
//! small CPU models is not the expensive part of this machine.

use ndarray::{Array2, Array3, Array4, ArrayD};
use ort::session::Session;
use ort::value::Tensor;

/// What the models were trained on. Not a preference.
pub const SAMPLE_RATE: u32 = 16_000;

/// How much audio is judged at once, and how often. Both from the daemon.
pub const WINDOW_SAMPLES: usize = 32_000; // 2.0s
pub const HOP_SAMPLES: usize = 8_000; // 0.5s

/// Mel frames per embedding, and how far that window steps.
const EMBED_WINDOW: usize = 76;
const EMBED_STRIDE: usize = 8;
/// Embeddings the wake model takes at once.
const SCORE_WINDOW: usize = 16;
/// Mel bins per frame.
const MEL_BINS: usize = 32;

/// int16 to the unit range. The wake classifier was trained on int16 audio;
/// the mel frontend in front of it was not.
const FULL_SCALE: f32 = 32_768.0;
/// openWakeWord's `melspec_transform`, applied outside the graph.
const MEL_SCALE: f32 = 10.0;
const MEL_OFFSET: f32 = 2.0;

pub struct Detector {
    mel: Session,
    embed: Session,
    wake: Session,
    /// The last two seconds heard, oldest first.
    heard: Vec<i16>,
}

impl Detector {
    pub fn load(models: &std::path::Path) -> ort::Result<Self> {
        Ok(Self {
            mel: Session::builder()?.commit_from_file(models.join("melspectrogram.onnx"))?,
            embed: Session::builder()?.commit_from_file(models.join("embedding_model.onnx"))?,
            wake: Session::builder()?.commit_from_file(models.join("marvi.onnx"))?,
            heard: Vec::with_capacity(WINDOW_SAMPLES),
        })
    }

    /// Feed a hop of audio. `None` until there is a full window to judge.
    ///
    /// `None` is not "did not hear her" — it is "cannot say yet", which for the
    /// first two seconds after start is the honest answer. A caller reporting
    /// that as a zero would be claiming silence it had not listened to.
    pub fn push(&mut self, samples: &[i16]) -> ort::Result<Option<f32>> {
        self.heard.extend_from_slice(samples);
        if self.heard.len() < WINDOW_SAMPLES {
            return Ok(None);
        }
        if self.heard.len() > WINDOW_SAMPLES {
            let extra = self.heard.len() - WINDOW_SAMPLES;
            self.heard.drain(..extra);
        }
        self.score_window().map(Some)
    }

    fn score_window(&mut self) -> ort::Result<f32> {
        let frames = self.mel_frames()?;
        if frames.len() < EMBED_WINDOW {
            return Ok(0.0);
        }
        let embeddings = self.embeddings(&frames)?;
        if embeddings.len() < SCORE_WINDOW {
            return Ok(0.0);
        }
        self.wake_score(&embeddings[embeddings.len() - SCORE_WINDOW..])
    }

    fn mel_frames(&mut self) -> ort::Result<Vec<[f32; MEL_BINS]>> {
        let audio: Vec<f32> = self.heard.iter().map(|&s| f32::from(s) / FULL_SCALE).collect();
        let input = Array2::from_shape_vec((1, audio.len()), audio)
            .expect("one row of exactly the samples held");
        let outputs = self.mel.run(ort::inputs!["input" => Tensor::from_array(input)?])?;
        let mel: ArrayD<f32> = outputs["output"].try_extract_array::<f32>()?.into_owned();

        // `(batch, 1, time, 32)`. Only the bins matter downstream, so this
        // reads it as a flat run of frames rather than carrying the shape.
        let flat = mel.as_slice().expect("contiguous mel output");
        Ok(flat
            .chunks_exact(MEL_BINS)
            .map(|chunk| {
                let mut frame = [0.0f32; MEL_BINS];
                for (slot, value) in frame.iter_mut().zip(chunk) {
                    *slot = value / MEL_SCALE + MEL_OFFSET;
                }
                frame
            })
            .collect())
    }

    fn embeddings(&mut self, frames: &[[f32; MEL_BINS]]) -> ort::Result<Vec<[f32; 96]>> {
        let mut found = Vec::new();
        let mut start = 0;
        while start + EMBED_WINDOW <= frames.len() {
            let mut window = Array4::<f32>::zeros((1, EMBED_WINDOW, MEL_BINS, 1));
            for (row, frame) in frames[start..start + EMBED_WINDOW].iter().enumerate() {
                for (column, value) in frame.iter().enumerate() {
                    window[[0, row, column, 0]] = *value;
                }
            }
            let outputs = self
                .embed
                .run(ort::inputs!["input_1" => Tensor::from_array(window)?])?;
            let produced: ArrayD<f32> =
                outputs["conv2d_19"].try_extract_array::<f32>()?.into_owned();
            let mut embedding = [0.0f32; 96];
            for (slot, value) in embedding
                .iter_mut()
                .zip(produced.as_slice().expect("contiguous embedding"))
            {
                *slot = *value;
            }
            found.push(embedding);
            start += EMBED_STRIDE;
        }
        Ok(found)
    }

    fn wake_score(&mut self, embeddings: &[[f32; 96]]) -> ort::Result<f32> {
        let mut window = Array3::<f32>::zeros((1, SCORE_WINDOW, 96));
        for (row, embedding) in embeddings.iter().enumerate() {
            for (column, value) in embedding.iter().enumerate() {
                window[[0, row, column]] = *value;
            }
        }
        let outputs = self
            .wake
            .run(ort::inputs!["embeddings" => Tensor::from_array(window)?])?;
        let scores: ArrayD<f32> = outputs["score"].try_extract_array::<f32>()?.into_owned();
        Ok(scores.as_slice().and_then(|s| s.first().copied()).unwrap_or(0.0))
    }
}
