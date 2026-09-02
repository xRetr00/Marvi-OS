"""The recogniser Marvi actually ships, over the same corpus as its challengers.

This is the row the first round was missing, and its absence is why that round
could not decide anything. Six candidates were measured, ranked, and all six
rejected -- against an incumbent whose only number, 13.7%, came from a
different corpus and which the report itself said "must not be compared
numerically with this pinned slice".

So the decision "no candidate is promoted" rested on exactly the comparison the
document forbade. If `parakeet-tdt-0.6b-v3` scores 40% here, Nemotron at 30%
was a clear win that got rejected; if it scores 15%, the rejection was right.
Nobody could tell.

It runs through `ParakeetSTT`'s own `StreamingTdtASR` at Marvi's configured
chunk, left context and lookahead, so what is measured is the recogniser as
Marvi runs it rather than a fresh offline decode of the same weights. Being
the incumbent is not a reason to measure it more kindly than the challengers.

    python evals\\parakeet_tdt_runner.py <manifest.jsonl> <corpus-dir> <out.jsonl>
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "services/agent/src"))

#: Marvi's own streaming geometry, read from the shipping recogniser rather
#: than restated here. A benchmark that picks its own chunk size measures a
#: configuration nobody runs.
from marvi_agent.parakeet_stt import (
    DEFAULT_LEFT_CONTEXT,
    chosen_model,
    chunk_seconds,
    lookahead_seconds,
    providers,
)
from stt_bench_common import read_pcm16, run, timed


#: The recogniser works on an 80 ms frame grid and refuses a request that is
#: not a whole number of frames, so blocks come off the recogniser rather than
#: from a duration chosen here. `ParakeetStream._run` does the same: the first
#: call wants a chunk plus the lookahead, every call after it wants a chunk.
class ShippingParakeet:
    """`StreamingTdtASR` driven exactly as `ParakeetStream` drives it."""

    def __init__(self, model_dir: Path) -> None:
        from streaming.streaming_asr import StreamingTdtASR

        self.model_dir = model_dir
        self.asr = StreamingTdtASR(
            str(model_dir),
            chunk_secs=chunk_seconds(),
            left_context_secs=DEFAULT_LEFT_CONTEXT,
            right_context_secs=lookahead_seconds(),
            providers=providers(),
        )

    def transcribe(self, audio_path: Path) -> dict[str, Any]:
        import numpy as np

        raw, audio_seconds = read_pcm16(audio_path)
        samples = np.frombuffer(raw, dtype=np.int16).astype(np.float32) / 32767.0
        # Fresh state per clip. A recogniser carrying the previous utterance
        # into the next one scores itself on a conversation the corpus does not
        # contain.
        self.asr.reset()

        compute_seconds = 0.0
        first_partial_ms: float | None = None
        partials = 0
        said = ""
        offset = 0
        first = True

        want = self.asr._initial_samples_needed
        while offset + want <= samples.size:
            block = samples[offset : offset + want]
            offset += want
            began = time.perf_counter()
            self.asr.process_chunk(block, False)
            compute_seconds += time.perf_counter() - began
            # The whole utterance re-read, never the per-chunk deltas glued
            # together: `process_chunk` returns the tokens decoded in *that*
            # chunk, so a word split across a boundary comes back as "actu"
            # then "ally". See `ParakeetStream._heard`.
            text = self.asr.get_full_text().strip()
            if text and text != said:
                said = text
                partials += 1
                if first_partial_ms is None:
                    # Audio presented to this point plus the compute spent
                    # reaching it: what a microphone feeding in real time would
                    # have waited. The definition every other runner uses.
                    presented = offset / 16_000.0
                    first_partial_ms = presented * 1_000.0 + compute_seconds * 1_000.0
            first = False
            want = self.asr.chunk_samples

        # The tail, with `last=True`, which is what flushes the decoder. A
        # benchmark that stops on the last whole block throws away the end of
        # every clip and calls the loss accuracy.
        tail = samples[offset:]
        began = time.perf_counter()
        self.asr.process_chunk(tail, True)
        final_seconds = time.perf_counter() - began
        compute_seconds += final_seconds
        text = self.asr.get_full_text().strip()
        if text and text != said:
            said = text
            partials += 1
        if first_partial_ms is None and said:
            first_partial_ms = audio_seconds * 1_000.0 + compute_seconds * 1_000.0

        return {
            "text": said,
            "inference_seconds": compute_seconds,
            "first_partial_ms": first_partial_ms,
            "final_after_eos_ms": final_seconds * 1_000.0,
            "partials": partials,
            "audio_seconds": audio_seconds,
            "feed_ms": round(chunk_seconds() * 1_000.0, 1),
            "first_block": bool(first),
        }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model", type=Path, help="defaults to the configured one")
    parser.add_argument("--limit", type=int)
    parser.add_argument(
        "--allow-cpu",
        action="store_true",
        help="measure on the processor, which is never a latency result",
    )
    args = parser.parse_args()

    # Refuse to quietly benchmark the wrong thing.
    #
    # `providers()` returns the processor unless `MARVI_STT_DEVICE` says cuda,
    # and this runner will happily transcribe all 200 clips that way: correct
    # text, RTF 0.539 where the recorded figure is 0.055, and nothing in the
    # output saying the run is not comparable except one field nobody reads.
    # It happened, and it took a spot-check of a log line to catch.
    #
    # A CPU run is a legitimate thing to want and a flag away. It is not a
    # legitimate default.
    if providers()[0] == "CPUExecutionProvider" and not args.allow_cpu:
        raise SystemExit(
            "ONNX Runtime would run on the processor, so the timings would not "
            "be comparable with any recorded result. Set MARVI_STT_DEVICE=cuda, "
            "or pass --allow-cpu to measure the processor deliberately."
        )

    model_dir = args.model or chosen_model()
    runtime, load_seconds, baseline = timed(lambda: ShippingParakeet(Path(model_dir)))
    run(
        args.manifest,
        args.corpus,
        args.output,
        engine=f"{Path(model_dir).name.removesuffix('-onnx')}-onnx-{providers()[0]}",
        semantics=(
            f"marvi-shipping-tdt-chunk{chunk_seconds()}s-"
            f"left{DEFAULT_LEFT_CONTEXT}s-lookahead{lookahead_seconds()}s"
        ),
        transcribe=runtime.transcribe,
        load_seconds=load_seconds,
        baseline_vram=baseline,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
