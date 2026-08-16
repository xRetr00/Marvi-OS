# Marvi Voice Runtime

This is deliberately a thin process boundary around the upstream
[`parakeet-rs`](https://github.com/altunenes/parakeet-rs) crate. It keeps the
stateful Nemotron ONNX session native on Windows while the official LiveKit
Agents SDK remains in Python.

The stdin/stdout protocol is newline-delimited JSON. Audio is 16 kHz mono
PCM16. Model inference state survives `audio` calls and is cleared by `flush`
or `reset`.

