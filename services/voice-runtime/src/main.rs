use std::env;
use std::io::{self, BufRead, Write};

use base64::{Engine as _, engine::general_purpose::STANDARD};
use parakeet_rs::{ExecutionConfig, ExecutionProvider, Nemotron};
use serde::{Deserialize, Serialize};

#[derive(Deserialize)]
#[serde(tag = "op", rename_all = "snake_case")]
enum Request {
    Audio { pcm16: String },
    Flush,
    Reset,
    Health,
}

#[derive(Serialize)]
struct Response<'a> {
    ok: bool,
    kind: &'a str,
    text: String,
    error: Option<String>,
}

fn respond(response: Response<'_>) -> Result<(), Box<dyn std::error::Error>> {
    let mut stdout = io::stdout().lock();
    serde_json::to_writer(&mut stdout, &response)?;
    stdout.write_all(b"\n")?;
    stdout.flush()?;
    Ok(())
}

fn error(message: impl Into<String>) -> Response<'static> {
    Response {
        ok: false,
        kind: "error",
        text: String::new(),
        error: Some(message.into()),
    }
}

fn decode_pcm16(value: &str) -> Result<Vec<f32>, String> {
    let bytes = STANDARD
        .decode(value)
        .map_err(|err| format!("invalid pcm16: {err}"))?;
    if bytes.len() % 2 != 0 {
        return Err("pcm16 payload has an odd byte count".to_owned());
    }
    Ok(bytes
        .chunks_exact(2)
        .map(|pair| i16::from_le_bytes([pair[0], pair[1]]) as f32 / 32768.0)
        .collect())
}

fn main() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = env::args().skip(1);
    let model_dir = args
        .next()
        .ok_or("usage: marvi-voice-runtime <model-dir> [language]")?;
    let language = args.next().unwrap_or_else(|| "tr-TR".to_owned());

    let execution = ExecutionConfig::new().with_execution_provider(ExecutionProvider::Cuda);
    let mut model = Nemotron::from_pretrained(model_dir, Some(execution))?;
    model.set_target_lang(&language)?;
    respond(Response {
        ok: true,
        kind: "ready",
        text: language.clone(),
        error: None,
    })?;

    for line in io::stdin().lock().lines() {
        let line = line?;
        let request: Request = match serde_json::from_str(&line) {
            Ok(request) => request,
            Err(err) => {
                respond(error(format!("invalid request: {err}")))?;
                continue;
            }
        };

        match request {
            Request::Audio { pcm16 } => {
                let samples = match decode_pcm16(&pcm16) {
                    Ok(samples) => samples,
                    Err(err) => {
                        respond(error(err))?;
                        continue;
                    }
                };
                match model.transcribe_chunk(&samples) {
                    Ok(text) => respond(Response {
                        ok: true,
                        kind: "partial",
                        text,
                        error: None,
                    })?,
                    Err(err) => respond(error(err.to_string()))?,
                }
            }
            Request::Flush => {
                // Nemotron buffers arbitrary feed sizes. Silence completes its final 560 ms window.
                let text = model.transcribe_chunk(&vec![0.0; model.chunk_samples()])?;
                model.reset();
                respond(Response {
                    ok: true,
                    kind: "final",
                    text,
                    error: None,
                })?;
            }
            Request::Reset => {
                model.reset();
                respond(Response {
                    ok: true,
                    kind: "reset",
                    text: String::new(),
                    error: None,
                })?;
            }
            Request::Health => {
                respond(Response {
                    ok: true,
                    kind: "healthy",
                    text: language.clone(),
                    error: None,
                })?;
            }
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn pcm16_transport_preserves_normalized_samples() {
        let encoded = STANDARD.encode([0, 0, 255, 127, 0, 128]);
        let samples = decode_pcm16(&encoded).unwrap();
        assert_eq!(samples[0], 0.0);
        assert!(samples[1] > 0.999);
        assert_eq!(samples[2], -1.0);
    }

    #[test]
    fn pcm16_transport_rejects_partial_samples() {
        assert!(decode_pcm16(&STANDARD.encode([1])).is_err());
    }
}
