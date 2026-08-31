from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import os
import sys
import tempfile
import uuid
from pathlib import Path

sys.stdout = sys.stderr


def _root() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
    return base / "Marvi-OS" / "models" / "tts" / "ctc-tts-f"


def _send(event: str, **values: object) -> None:
    sys.__stdout__.write(json.dumps({"event": event, **values}) + "\n")
    sys.__stdout__.flush()


def _config(source: Path, model: Path) -> dict[str, object]:
    path = (
        model
        / "singlespeaker"
        / "ctcttsf"
        / "o19_1750_wavlarge_feature_next0_word_fw1.json"
    )
    config = json.loads(path.read_text("utf-8"))
    config["encoder"]["model_path"] = str(model / "best-10.pt")
    config["encoder"]["fbank_config"] = str(model / "fbank.conf")
    config["encoder"]["phonetisaurus_model_path"] = str(model / "model.fst")
    config["tokenizer"]["file"] = str(source / "config" / "tokenizer_updated.tknz")
    config["data"]["lexicon_path"] = str(model / "llmvox_lexicon.txt")
    config["nac"]["nac_config"] = str(
        source
        / "WavTokenizer"
        / "configs"
        / "wavtokenizer_smalldata_frame75_3s_nq1_code4096_dim512_kmeans200_attn.yaml"
    )
    config["nac"]["nac_model"] = str(
        _root() / "wavtokenizer" / "wavtokenizer_large_speech_320_v2.ckpt"
    )
    config["inference"]["model_path"] = str(
        model / "singlespeaker" / "ctcttsf" / "ckpt.pt"
    )
    # Both upstream streaming decoders share the target RTX 3060.
    config["inference"]["tts_device_1"] = 0
    config["inference"]["tts_device_2"] = 0
    config["inference"]["enable_chunked_decode"] = True
    return config


async def _synth(
    module: object, config: dict[str, object], text: str, *, emit: bool = True
) -> None:
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as output:
        wav_path = output.name
    try:
        # The released `tts()` helper force-restarts both decoder processes on
        # every request. Marvi speaks one clause at a time, so that would reload
        # the model between clauses. Use the pinned module's queue seam directly
        # and keep its workers warm for this host's lifetime.
        module.config = config
        module.init_models(force_restart=False)
        request_id = uuid.uuid4().hex
        payload = {
            "command": "synthesize",
            "request_id": request_id,
            "text": text,
            "enable_chunked_decode": True,
            "speech_prompt": None,
            "text_prompt": None,
        }
        module.worker_request_queue_1.put(payload)
        module.worker_request_queue_2.put(payload)
        stream = module.audio_generator_async(
            module.worker_output_queue_1,
            module.worker_output_queue_2,
            module.worker_control_queue,
            request_id,
            wav_path,
            [module.worker_process_1, module.worker_process_2],
            enable_smoothing=False,
        )
        import numpy as np

        async for raw in stream:
            if raw is None:
                continue
            samples = np.frombuffer(raw, dtype=np.float32)
            pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16).tobytes()
            if emit:
                _send("chunk", pcm=base64.b64encode(pcm).decode("ascii"))
    finally:
        Path(wav_path).unlink(missing_ok=True)


def main() -> None:
    source = _root() / "source"
    model = _root() / "model"
    sys.path.insert(0, str(source))
    try:
        with contextlib.redirect_stdout(sys.stderr):
            import streaming_inferencer

            config = _config(source, model)
            asyncio.run(
                _synth(streaming_inferencer, config, "Marvi is ready.", emit=False)
            )
        _send("ready", sample_rate=24000)
    except Exception as exc:  # noqa: BLE001 - process boundary must report upstream failures
        _send("error", error=f"CTC-TTS-F failed to load: {exc}")
        return
    for line in sys.stdin:
        try:
            request = json.loads(line)
            with contextlib.redirect_stdout(sys.stderr):
                asyncio.run(
                    _synth(streaming_inferencer, config, str(request.get("text") or ""))
                )
            _send("done")
        except Exception as exc:  # noqa: BLE001 - keep the host alive for the next request
            _send("error", error=str(exc))


if __name__ == "__main__":
    main()
