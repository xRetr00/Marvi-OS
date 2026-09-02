"""NVIDIA Canary-1B-v2 over Marvi's accented-English corpus.

Canary is an encoder-decoder ASR/AST model, not a streaming recogniser. That
matters more than its accuracy here, and the report must say so: there is no
cache-aware state to feed 160 ms at a time, so it cannot produce a partial
before the utterance ends. Its first-partial figure is therefore its *final*
figure, and it fails Marvi's partial gate by construction rather than by
measurement.

It is in the round anyway for one reason: it sets the accuracy ceiling. If a
non-streaming 1B model scores 18% on Arabic-accented English and every
streaming candidate scores 35%, the gap is what streaming costs on this corpus
-- which is the number that decides whether the gate is worth holding. A
bakeoff of streaming models alone cannot see that.

Run in an isolated environment; NeMo pulls a large dependency tree that must
not land in the Agent's:

    python evals\\canary_runner.py <manifest.jsonl> <corpus-dir> <out.jsonl>
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from stt_bench_common import read_pcm16, run, timed

MODEL = "nvidia/canary-1b-v2"

#: Canary decodes a whole utterance. Batching would be faster and would also
#: measure something Marvi cannot use: a turn arrives alone.
BATCH = 1


class Canary:
    """One `EncDecMultiTaskModel`, transcribing one clip at a time."""

    def __init__(self, model_id: str, device: str) -> None:
        from nemo.collections.asr.models import EncDecMultiTaskModel

        self.model = EncDecMultiTaskModel.from_pretrained(model_id)
        # Greedy, so the number is the model rather than a beam search nobody
        # would run inside a spoken turn.
        config = self.model.cfg.decoding
        config.beam.beam_size = 1
        self.model.change_decoding_strategy(config)
        self.model = self.model.to(device).eval()
        self.device = device

    def transcribe(self, audio_path: Path) -> dict[str, Any]:
        import torch

        _, audio_seconds = read_pcm16(audio_path)
        began = time.perf_counter()
        with torch.inference_mode():
            found = self.model.transcribe(
                [str(audio_path)],
                batch_size=BATCH,
                source_lang="en",
                target_lang="en",
                task="asr",
                pnc="no",
                verbose=False,
            )
        compute_seconds = time.perf_counter() - began
        said = _said(found)

        return {
            "text": said,
            "inference_seconds": compute_seconds,
            # Not a streaming partial. Canary has no incremental state, so the
            # earliest anything exists is after the whole clip has been read
            # and decoded -- recorded as such rather than left blank, because
            # a blank would score as "no partial gate data" instead of "cannot
            # produce a partial".
            "first_partial_ms": audio_seconds * 1_000.0 + compute_seconds * 1_000.0,
            "final_after_eos_ms": compute_seconds * 1_000.0,
            "partials": 1 if said else 0,
            "audio_seconds": audio_seconds,
            "feed_ms": None,
            "streaming": False,
        }


def _said(found: Any) -> str:
    """NeMo has returned strings and hypothesis objects across versions."""
    if not found:
        return ""
    first = found[0]
    if isinstance(first, str):
        return first.strip()
    for name in ("text", "pred_text"):
        value = getattr(first, name, None)
        if isinstance(value, str):
            return value.strip()
    return str(first).strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    runtime, load_seconds, baseline = timed(lambda: Canary(args.model, args.device))
    run(
        args.manifest,
        args.corpus,
        args.output,
        engine=f"canary-1b-v2-nemo-{args.device}",
        # Named for what it is. The first round's table has a "streaming
        # behavior exercised" column, and the honest entry here is that none
        # was: a row that quietly reports offline numbers under a streaming
        # heading is how a benchmark starts lying.
        semantics="offline-encoder-decoder-whole-utterance-no-streaming",
        transcribe=runtime.transcribe,
        load_seconds=load_seconds,
        baseline_vram=baseline,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
