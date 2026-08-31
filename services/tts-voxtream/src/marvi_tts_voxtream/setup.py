from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from .host import _root

SOURCE = "https://github.com/herimor/voxtream.git"
SOURCE_REVISION = "8ec2d62159dae4716ae7058827244a962d40603c"
MODEL_REVISION = "49addec130217e8e9e82a6f49437c315c5c851fc"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    marker = _root() / ".marvi-revision"
    wanted = f"{SOURCE_REVISION}\n{MODEL_REVISION}\n"
    if args.check:
        raise SystemExit(0 if marker.is_file() and marker.read_text() == wanted else 1)

    from huggingface_hub import snapshot_download
    from huggingface_hub.file_download import are_symlinks_supported

    _root().mkdir(parents=True, exist_ok=True)
    cache = _root() / "huggingface" / "hub"
    # Prime Hugging Face's process-local capability cache before its parallel
    # downloader starts. Without this, first-use threads can race on Windows
    # and attempt a privileged symlink after another thread detected that only
    # the copy fallback is available.
    are_symlinks_supported(str(cache))
    snapshot_download(
        "herimor/voxtream2",
        revision=MODEL_REVISION,
        cache_dir=cache,
    )
    staging = Path(tempfile.mkdtemp(prefix="marvi-voxtream-"))
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
    # Populate every transitive model cache during Setup. SpeechGenerator also
    # needs Mimi and ReDimNet; allowing those to appear on the first spoken turn
    # would make offline voice fail after Setup had claimed success.
    os.environ["HF_HOME"] = str(_root() / "huggingface")
    import torch._dynamo
    from voxtream.config import SpeechGeneratorConfig
    from voxtream.generator import SpeechGenerator

    torch._dynamo.config.suppress_errors = True
    config = SpeechGeneratorConfig(
        **json.loads((target / "configs" / "generator.json").read_text("utf-8"))
    )
    speaking_rate = json.loads(
        (target / "configs" / "speaking_rate.json").read_text("utf-8")
    )
    SpeechGenerator(config, speaking_rate, compile=False)
    marker.write_text(wanted, encoding="utf-8")


if __name__ == "__main__":
    main()
