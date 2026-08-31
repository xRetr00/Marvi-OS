from __future__ import annotations

import argparse
import shutil
import subprocess
import tempfile
from pathlib import Path

from .host import _root

SOURCE = "https://github.com/THU-SPMI/CTC-TTS.git"
SOURCE_REVISION = "7b308b7762564a53e398482a5ec0685d4d9c7e9f"
MODEL_REVISION = "1e568e2a03d9664037344fbccf23163a5b9b0cf7"
CODEC_REVISION = "f0eafde4078a49b3875d79d33632a252dcd02f60"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    marker = _root() / ".marvi-revision"
    wanted = f"{SOURCE_REVISION}\n{MODEL_REVISION}\n{CODEC_REVISION}\n"
    if args.check:
        raise SystemExit(0 if marker.is_file() and marker.read_text() == wanted else 1)
    from huggingface_hub import snapshot_download

    _root().mkdir(parents=True, exist_ok=True)
    snapshot_download(
        "THU-SPMI/CTC-TTS",
        revision=MODEL_REVISION,
        local_dir=_root() / "model",
        allow_patterns=[
            "best-10.pt",
            "fbank.conf",
            "llmvox_lexicon.txt",
            "model.fst",
            "singlespeaker/ctcttsf/**",
        ],
    )
    snapshot_download(
        "novateur/WavTokenizer-large-speech-75token",
        revision=CODEC_REVISION,
        local_dir=_root() / "wavtokenizer",
    )
    staging = Path(tempfile.mkdtemp(prefix="marvi-ctc-"))
    try:
        subprocess.run(["git", "init", "--quiet", str(staging)], check=True)
        subprocess.run(
            ["git", "-C", str(staging), "remote", "add", "origin", SOURCE], check=True
        )
        subprocess.run(
            [
                "git",
                "-C",
                str(staging),
                "fetch",
                "--depth",
                "1",
                "origin",
                SOURCE_REVISION,
            ],
            check=True,
        )
        subprocess.run(
            ["git", "-C", str(staging), "checkout", "--quiet", "FETCH_HEAD"], check=True
        )
        target = _root() / "source"
        if target.exists():
            shutil.rmtree(target)
        shutil.copytree(staging, target, ignore=shutil.ignore_patterns(".git"))
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    marker.write_text(wanted, encoding="utf-8")


if __name__ == "__main__":
    main()
