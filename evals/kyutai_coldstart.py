"""Why Kyutai looks worse in Marvi's benchmark than in Kyutai's own demo.

The owner's transcript from the official web demo is coherent and arrives in
real time. Marvi's benchmark scored the same model at 40.73% WER with eleven of
162 clips returning nothing at all. Both cannot be describing the same thing,
so one of them is measuring something else.

The obvious suspect is the shape of the input. The demo is one continuous
stream: the model has been running for a minute by the time you say anything
interesting, and its state carries. The benchmark calls `reset_streaming()`
before every clip, so a 2-second utterance is decoded by a model that has
existed for 2 seconds -- a cold start every time, 162 times.

This runs the clips that came back empty three ways and prints what each
produces:

    isolated    exactly as the benchmark does it
    prefixed    a second of silence first, so the model has something to settle
                into before the speech starts
    continuous  all of them as one stream, state carried between them, which is
                what the demo does

If prefixed or continuous produce text where isolated produced none, the
benchmark was measuring cold-start behaviour and the model is fine.

    python evals\\kyutai_coldstart.py <manifest.jsonl> <corpus> <model> <predictions.jsonl>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

os.environ.setdefault("NO_TORCH_COMPILE", "1")

sys.path.insert(0, str(Path(__file__).resolve().parent))

#: A second, which is twice the model's own `audio_delay_seconds` of 0.5. The
#: point is not the exact number: it is whether *any* lead-in changes the
#: answer.
PREFIX_SECONDS = 1.0


def main() -> None:
    import sphn
    import torch
    from moshi.models import LMGen, loaders

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("model", type=Path)
    parser.add_argument("predictions", type=Path, help="a scored run, to find the empties")
    parser.add_argument("--limit", type=int, default=8)
    args = parser.parse_args()

    manifest = {
        json.loads(line)["id"]: json.loads(line)
        for line in args.manifest.read_text(encoding="utf-8").splitlines()
    }
    empty = [
        json.loads(line)["id"]
        for line in args.predictions.read_text(encoding="utf-8").splitlines()
        if not str(json.loads(line).get("text") or "").strip()
    ][: args.limit]
    if not empty:
        print("no empty clips in that run; nothing to explain")
        return
    print(f"{len(empty)} clips that came back empty\n")

    model = args.model.resolve()
    checkpoint = loaders.CheckpointInfo.from_hf_repo(
        "kyutai/stt-1b-en_fr",
        config_path=model / "config.json",
        moshi_weights=model / "model.safetensors",
        mimi_weights=model / "mimi-pytorch-e351c8d8@125.safetensors",
        tokenizer=model / "tokenizer_en_fr_audio_8000.model",
    )
    mimi = checkpoint.get_mimi(device="cuda")
    tokenizer = checkpoint.get_text_tokenizer()
    lm = checkpoint.get_moshi(device="cuda")
    lm_gen = LMGen(lm, temp=0, temp_text=0, use_sampling=False)
    frame = int(mimi.sample_rate / mimi.frame_rate)
    flush = int((float(checkpoint.stt_config["audio_delay_seconds"]) + 1.0) * mimi.sample_rate)
    mimi.streaming_forever(1)
    lm_gen.streaming_forever(1)

    def read(clip_id: str) -> torch.Tensor:
        pcm, _ = sphn.read(
            str(args.corpus / manifest[clip_id]["audio"]), sample_rate=mimi.sample_rate
        )
        return torch.from_numpy(pcm[None, 0:1]).to(device="cuda")

    @torch.inference_mode()
    def decode(audio: torch.Tensor, fresh: bool) -> tuple[str, float]:
        if fresh:
            mimi.reset_streaming()
            lm_gen.reset_streaming()
        said: list[str] = []
        began = time.perf_counter()
        first = True
        for offset in range(0, audio.shape[-1], frame):
            chunk = audio[:, :, offset : offset + frame]
            if chunk.shape[-1] != frame:
                break
            codes = mimi.encode(chunk)
            if first:
                lm_gen.step(codes)
                first = False
            tokens = lm_gen.step(codes)
            if tokens is None:
                continue
            token = tokens[0, 0, 0].item()
            if token not in (0, 3):
                said.append(tokenizer.id_to_piece(token).replace("▁", " "))
        return "".join(said).strip(), time.perf_counter() - began

    silence = torch.zeros(
        1, 1, int(PREFIX_SECONDS * mimi.sample_rate), device="cuda"
    )
    pad = torch.zeros(1, 1, flush, device="cuda")

    print(f"{'clip':<22} {'isolated':<30} {'prefixed':<30} continuous")
    print("-" * 110)
    # Continuous first: one stream, every clip in order, state carried.
    mimi.reset_streaming()
    lm_gen.reset_streaming()
    running: dict[str, str] = {}
    for clip_id in empty:
        text, _ = decode(torch.cat([read(clip_id), pad], dim=-1), fresh=False)
        running[clip_id] = text

    for clip_id in empty:
        audio = read(clip_id)
        alone, _ = decode(torch.cat([audio, pad], dim=-1), fresh=True)
        lead, _ = decode(torch.cat([silence, audio, pad], dim=-1), fresh=True)
        print(
            f"{clip_id:<22} {(alone or '(nothing)')[:28]:<30} "
            f"{(lead or '(nothing)')[:28]:<30} {(running[clip_id] or '(nothing)')[:34]}"
        )
        print(f"{'':<22} ref: {manifest[clip_id]['reference'][:80]}")


if __name__ == "__main__":
    main()
