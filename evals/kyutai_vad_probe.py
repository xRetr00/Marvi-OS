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
    #: Consecutive frames above the threshold before the crossing counts. The
    #: heads spike for a frame or two mid-utterance; a sustained run is what
    #: distinguishes "they stopped" from "they breathed".
    parser.add_argument("--hold", type=int, default=1)
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

    print(f"{heads} pause heads, threshold {args.threshold}, hold {args.hold} frame(s)")
    print(f"{'clip':<22} {'last word':>10} {'0.5s':>8} {'1.0s':>8} {'2.0s':>8} {'3.0s':>8}")
    print("-" * 70)

    leads: dict[int, list[float]] = {index: [] for index in range(heads)}
    #: Crossings before the last one. Each is a turn this head would have cut
    #: short if the first crossing ended the turn.
    early: dict[int, int] = {index: 0 for index in range(heads)}
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
        last_fired: dict[int, float | None] = {index: None for index in range(heads)}
        spikes: dict[int, int] = {index: 0 for index in range(heads)}
        was_high: dict[int, bool] = {index: False for index in range(heads)}
        run_length: dict[int, int] = {index: 0 for index in range(heads)}
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
                if float(head[0, 0, 0].item()) > args.threshold:
                    run_length[index] += 1
                else:
                    run_length[index] = 0
                high = run_length[index] >= args.hold
                # Every crossing, not the first.
                #
                # The first version of this took the first crossing after the
                # first word and reported a median of -0.76s, which read as
                # "the model calls the turn before the sentence even lands".
                # It was measuring mid-utterance pauses: one clip crossed 8.9
                # seconds before its last word. A signal used as end-of-turn
                # has to be judged on how often it is wrong, not on how early
                # it can be right, so this counts the spikes and records the
                # last one as well as the first.
                if high and not was_high[index]:
                    spikes[index] += 1
                    if fired[index] is None:
                        fired[index] = at
                    last_fired[index] = at
                was_high[index] = high

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
            when = last_fired[index]
            if when is None:
                cells.append("never")
                continue
            leads[index].append(when - last_word)
            early[index] += max(0, spikes[index] - 1)
            cells.append(f"{when - last_word:+.2f}s x{spikes[index]}")
        print(
            f"{row['id'][:22]:<22} {last_word:9.2f}s "
            + " ".join(f"{cell:>12}" for cell in cells)
        )

    print()
    print("last crossing relative to the last word, and premature crossings:")
    for index, label in enumerate(("0.5s", "1.0s", "2.0s", "3.0s")[:heads]):
        got = leads[index]
        if not got:
            print(f"  head {index} ({label}): never fired")
            continue
        print(
            f"  head {index} ({label}): median {statistics.median(got):+.2f}s, "
            f"{early[index]} premature crossing(s) across {len(got)} clips"
        )
    print()
    print("Marvi's fallback timer is +0.60s. A head only beats it if its median")
    print("is lower AND its premature count is zero -- a head that fires early")
    print("cuts somebody off mid-sentence, which is worse than waiting.")


if __name__ == "__main__":
    main()
