"""Does the semantic VAD say anything, and does it say it sooner than a timer?

Wiring an end-of-turn signal that never fires is worse than not having one: the
turn still ends, on the fallback timer, and the log says the model decided it.
So before this goes anywhere near a session, the question is measured.

For each clip it reports, per pause head:

    fired      whether the probability ever crossed the threshold
    at         when, in seconds from the start of the clip
    speech     when the last word was transcribed

`at - speech` is the thing worth having. Negative or near zero means the model
called the turn as the sentence landed; a full second means it waited for
silence like everything else and the head is decoration at this threshold.

    python evals/kyutai_vad_probe.py <manifest.jsonl> <corpus> <model> [--limit 12]
"""

from __future__ import annotations

import argparse
import json
import os
import statistics
import sys
from pathlib import Path

os.environ.setdefault("NO_TORCH_COMPILE", "1")
sys.path.insert(0, str(Path(__file__).resolve().parent))

#: Kyutai's Rust example uses 0.5; their issue tracker mentions 0.6 in passing.
THRESHOLD = 0.5

#: A second of silence in front, because this model emits nothing at all when
#: the audio starts mid-word. See `kyutai_stt.PREFIX_SECONDS`.
PREFIX_SECONDS = 1.0


def main() -> None:
    import sphn
    import torch
    from moshi.models import LMGen, loaders

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("model", type=Path)
    parser.add_argument("--limit", type=int, default=12)
    parser.add_argument("--threshold", type=float, default=THRESHOLD)
    args = parser.parse_args()

    rows = [
        json.loads(line)
        for line in args.manifest.read_text(encoding="utf-8").splitlines()
    ][: args.limit]

    checkpoint = loaders.CheckpointInfo.from_hf_repo(
        "kyutai/stt-1b-en_fr-candle",
        config_path=args.model / "config.json",
        moshi_weights=args.model / "model.safetensors",
        mimi_weights=args.model / "mimi-pytorch-e351c8d8@125.safetensors",
        tokenizer=args.model / "tokenizer_en_fr_audio_8000.model",
    )
    mimi = checkpoint.get_mimi(device="cuda")
    tokenizer = checkpoint.get_text_tokenizer()
    lm = checkpoint.get_moshi(device="cuda")
    heads = len(getattr(lm, "extra_heads", ()) or ())
    if not heads:
        raise SystemExit("this checkpoint has no VAD heads; use stt-1b-en_fr-candle")
    gen = LMGen(lm, temp=0, temp_text=0, use_sampling=False)
    frame = int(mimi.sample_rate / mimi.frame_rate)
    seconds_per_frame = frame / mimi.sample_rate
    mimi.streaming_forever(1)
    gen.streaming_forever(1)
    prefix_frames = int(PREFIX_SECONDS / seconds_per_frame)

    print(f"{heads} pause heads, threshold {args.threshold}")
    print(f"{'clip':<22} {'last word':>10} {'0.5s':>8} {'1.0s':>8} {'2.0s':>8} {'3.0s':>8}")
    print("-" * 70)

    leads: dict[int, list[float]] = {index: [] for index in range(heads)}
    silent = 0

    for row in rows:
        pcm, _ = sphn.read(
            str(args.corpus / row["audio"]), sample_rate=mimi.sample_rate
        )
        audio = torch.from_numpy(pcm[None, 0:1]).to(device="cuda")
        quiet = torch.zeros(1, 1, frame, device="cuda")
        # Inside inference mode, because the streaming state was allocated
        # inside it and PyTorch refuses an in-place update to an inference
        # tensor from outside.
        with torch.inference_mode():
            mimi.reset_streaming()
            gen.reset_streaming()

        fired: dict[int, float | None] = {index: None for index in range(heads)}
        last_word: float | None = None
        said: list[str] = []
        step = 0
        first = True

        def run(chunk: torch.Tensor) -> None:
            nonlocal first, last_word, step
            with torch.inference_mode():
                codes = mimi.encode(chunk)
                if first:
                    gen.step(codes)
                    first = False
                found = gen.step_with_extra_heads(codes)
            step += 1
            if found is None:
                return
            tokens, extra = found
            # Time measured from the start of the real audio, so the silence
            # prefix does not make every number look a second late.
            at = (step - prefix_frames) * seconds_per_frame
            token = int(tokens[0, 0].item())
            if token not in (0, 3):
                piece = tokenizer.id_to_piece(token).replace("▁", " ")
                if piece.strip():
                    said.append(piece)
                    last_word = at
            # Only after something has been said.
            #
            # The heads are pause detectors, so they are high during the
            # silence prefix -- correctly, and uselessly: the first crossing on
            # every clip was a second before the first word. An end-of-turn
            # before the turn has begun is not a turn ending, and this is the
            # same guard the adapter carries.
            if last_word is None:
                return
            for index, head in enumerate(extra):
                if fired[index] is None and float(head[0, 0, 0].item()) > args.threshold:
                    fired[index] = at

        for _ in range(prefix_frames):
            run(quiet)
        for offset in range(0, audio.shape[-1], frame):
            chunk = audio[:, :, offset : offset + frame]
            if chunk.shape[-1] != frame:
                break
            run(chunk)
        # And the flush, where a turn ending after the audio would show up.
        for _ in range(int(checkpoint.stt_config["audio_delay_seconds"] / seconds_per_frame) + 1):
            run(quiet)

        if last_word is None:
            silent += 1
            continue
        cells = []
        for index in range(heads):
            when = fired[index]
            if when is None:
                cells.append("never")
                continue
            leads[index].append(when - last_word)
            cells.append(f"{when - last_word:+.2f}s")
        print(
            f"{row['id'][:22]:<22} {last_word:9.2f}s "
            + " ".join(f"{cell:>8}" for cell in cells)
        )

    print()
    print("after the last word, median over the clips that fired:")
    for index, label in enumerate(("0.5s", "1.0s", "2.0s", "3.0s")[:heads]):
        got = leads[index]
        if not got:
            print(f"  head {index} ({label}): never fired")
            continue
        print(
            f"  head {index} ({label}): {statistics.median(got):+.2f}s "
            f"on {len(got)}/{len(rows) - silent} clips"
        )
    print()
    print("Marvi's fallback timer is +0.60s. A head with a median below that")
    print("ends the turn sooner than every other recogniser here.")


if __name__ == "__main__":
    main()
