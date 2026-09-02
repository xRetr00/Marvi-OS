"""Parakeet Unified EN 0.6B, offline and buffered-streaming.

Not a newer Parakeet TDT. A different model, published April 2026: one
FastConformer-RNNT trained jointly for offline *and* streaming, where the
shipping recogniser is offline-only and the streaming one is a separate
cache-aware model.

## What is being asked

The shipping recogniser wins accuracy and end-of-speech latency on Marvi's own
corpus and loses badly on one number: its first useful partial arrives at
4,115 ms. Subtitles crawl. NVIDIA's card claims this model does 6.70% WER at
240 ms of algorithmic latency, which would fix exactly that.

The claim to check is not the accuracy. It is whether 240 ms of *algorithmic*
latency survives contact with a 3060, because the card is explicit about how
the streaming works:

    "The current inference pipeline supports only buffered streaming (left
    context is recomputed for each chunk)"

Left context defaults to 5.6 s. Recomputing 5.6 s of encoder for every 80 ms
chunk is seventy times realtime before a word is decoded. That is the thing to
measure, and it is why this runner reports both modes:

    offline     the ceiling. Does it beat the incumbent on accuracy at all?
    streaming   the question. Is the low-latency mode usable on this card?

An offline win with an unusable streaming mode means the model is interesting
and not the answer. Both numbers are needed to say which.

    python evals/parakeet_unified_runner.py <manifest> <corpus> <out.jsonl> \\
        [--mode offline|streaming] [--chunk 0.16] [--buffer 2.0]
"""

from __future__ import annotations

import argparse
import contextlib
import math
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))

from stt_bench_common import read_pcm16, run, timed

MODEL = "nvidia/parakeet-unified-en-0.6b"

#: The card's recommended shapes, as (chunk, right context) in seconds:
#:
#:     160 ms   0.08 + 0.08
#:     240 ms   0.08 + 0.16
#:     560 ms   0.16 + 0.40
#:    2080 ms   1.04 + 1.04
#:
#: Buffered streaming re-encodes the whole window per chunk, so the compute
#: cost is (left + chunk + right) / chunk. The card's own default left context
#: of 5.6 s at the 240 ms shape is 73x realtime, which is not a configuration
#: anybody can run; the defaults here are the 560 ms shape with a shortened
#: left context, which is the fastest one with a chance of keeping up.
DEFAULT_CHUNK = 0.16
DEFAULT_BUFFER = 2.0


class UnifiedParakeet:
    """One model, driven offline or through NeMo's buffered streaming helper."""

    def __init__(self, model_id: str, mode: str, chunk: float, buffer: float) -> None:
        import torch
        from nemo.collections.asr.models import ASRModel

        self.mode = mode
        self.chunk = chunk
        self.buffer = buffer
        self.model = ASRModel.from_pretrained(model_id)
        self.model.eval()
        # This checkpoint ships no `validation_ds`, and NeMo's transcribe path
        # reads `self.cfg.validation_ds.get(...)` unconditionally:
        #
        #     AttributeError: 'NoneType' object has no attribute 'get'
        #
        # on every clip, before any audio is touched. Supplied here rather than
        # worked around per call, because it is a hole in the published config
        # and not a choice about how to transcribe.
        if getattr(self.model.cfg, "validation_ds", None) is None:
            from omegaconf import OmegaConf, open_dict

            with open_dict(self.model.cfg):
                self.model.cfg.validation_ds = OmegaConf.create(
                    {"use_start_end_token": False}
                )
        if torch.cuda.is_available():
            self.model = self.model.cuda()
        self._streamer: Any = None
        if mode == "streaming":
            # `BatchedFrameASRRNNT`, not `FrameBatchChunkedRNNT`.
            #
            # The chunked one decodes every buffer from scratch and joins the
            # results, which on a 0.16 s chunk produced
            #
            #     It    But An       How         Yes    I         I       M
            #
            # -- a word or two per chunk with no merging. This is the class
            # NeMo's own `speech_to_text_buffered_infer_rnnt.py` uses, and it
            # keeps only the middle tokens of each buffer, which is what makes
            # buffered streaming produce a sentence rather than confetti.
            # Alignments, which buffered merging needs and greedy decoding
            # does not produce by default:
            #
            #     if delay == len(alignment):
            #     TypeError: object of type 'NoneType' has no len()
            #
            # on every clip. The merge keeps the middle tokens of each buffer,
            # and it can only find the middle if it knows where the tokens are.
            import copy

            from nemo.collections.asr.parts.utils.streaming_utils import (
                BatchedFrameASRRNNT,
            )
            from omegaconf import open_dict as _open

            decoding = copy.deepcopy(self.model.cfg.decoding)
            with _open(decoding):
                decoding.strategy = "greedy_batch"
                decoding.preserve_alignments = True
                decoding.fused_batch_size = -1
            self.model.change_decoding_strategy(decoding)

            self._streamer = BatchedFrameASRRNNT(
                asr_model=self.model,
                frame_len=chunk,
                total_buffer=buffer,
                batch_size=1,
            )
            # The merge parameters, computed the way upstream's script does.
            # `model_stride_in_secs` is the encoder's output rate: 8x
            # subsampling on a 10 ms window is 0.08 s per encoder frame.
            self.stride = 0.08
            self.tokens_per_chunk = math.ceil(chunk / self.stride)
            self.mid_delay = math.ceil(
                (chunk + (buffer - chunk) / 2) / self.stride
            )

    def transcribe(self, audio_path: Path) -> dict[str, object]:
        # `(bytes, seconds)`, not `(samples, rate)`. Unpacked as the latter,
        # every clip reported 32,000 seconds of audio -- bytes divided by
        # duration -- which made RTF 0.000 and a first partial of nine hours.
        # The transcripts were unaffected, so the accuracy columns were right
        # while every latency column beside them was nonsense.
        _audio, audio_seconds = read_pcm16(audio_path)
        began = time.perf_counter()
        if self.mode == "offline":
            with contextlib.redirect_stdout(sys.stderr):
                found = self.model.transcribe([str(audio_path)], verbose=False)
            text = _text_of(found)
            compute = time.perf_counter() - began
            return {
                "text": text,
                "inference_seconds": compute,
                # Offline sees the whole clip before it says anything, so the
                # earliest a partial could exist is the end of the audio plus
                # the compute. Reported rather than left blank, because a blank
                # reads as "not measured" next to engines that do stream.
                "first_partial_ms": (audio_seconds + compute) * 1_000.0,
                "final_after_eos_ms": compute * 1_000.0,
                "partials": 1,
                "audio_seconds": audio_seconds,
                "feed_ms": audio_seconds * 1_000.0,
            }

        self._streamer.reset()
        with contextlib.redirect_stdout(sys.stderr):
            # A list, not a path. `BatchedFrameASRRNNT.read_audio_file`
            # asserts `len(audio_filepath) == self.batch_size`, so a string is
            # measured in characters -- the assertion fails inside NeMo, gets
            # swallowed, and every clip comes back empty with no error on the
            # row. Three chunk configurations were blamed before the assert
            # was found.
            self._streamer.read_audio_file(
                [str(audio_path)], delay=self.mid_delay, model_stride_in_secs=self.stride
            )
            text = self._streamer.transcribe(self.tokens_per_chunk, self.mid_delay)
        compute = time.perf_counter() - began
        return {
            "text": _text_of(text),
            "inference_seconds": compute,
            # The helper transcribes the whole file rather than handing back
            # partials as they land, so a genuine first-partial cannot be
            # measured here. The chunk plus its share of the compute is the
            # honest floor, and it is labelled as such in the report.
            "first_partial_ms": (self.chunk + compute * self.chunk / max(audio_seconds, 0.01))
            * 1_000.0,
            "final_after_eos_ms": compute / max(audio_seconds / self.chunk, 1) * 1_000.0,
            "partials": max(1, int(audio_seconds / self.chunk)),
            "audio_seconds": audio_seconds,
            "feed_ms": self.chunk * 1_000.0,
        }


def _text_of(found: Any) -> str:
    """NeMo returns strings, Hypotheses, or lists of either, by version."""
    if isinstance(found, list):
        found = found[0] if found else ""
    return str(getattr(found, "text", found) or "").strip()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("corpus", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--mode", choices=("offline", "streaming"), default="offline")
    parser.add_argument("--chunk", type=float, default=DEFAULT_CHUNK)
    parser.add_argument("--buffer", type=float, default=DEFAULT_BUFFER)
    parser.add_argument("--limit", type=int)
    args = parser.parse_args()

    runtime, load_seconds, baseline = timed(
        lambda: UnifiedParakeet(args.model, args.mode, args.chunk, args.buffer)
    )
    shape = (
        "offline-whole-utterance"
        if args.mode == "offline"
        else f"buffered-streaming-chunk{args.chunk}s-buffer{args.buffer}s"
    )
    run(
        args.manifest,
        args.corpus,
        args.output,
        engine=f"parakeet-unified-en-0.6b-nemo-{args.mode}",
        semantics=shape,
        transcribe=runtime.transcribe,
        load_seconds=load_seconds,
        baseline_vram=baseline,
        limit=args.limit,
    )


if __name__ == "__main__":
    main()
