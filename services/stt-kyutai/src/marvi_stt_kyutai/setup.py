from __future__ import annotations

import argparse

from .host import _root

#: `kyutai/stt-1b-en_fr-candle`, not `kyutai/stt-1b-en_fr`.
#:
#: They publish the same model under both names and only this one carries the
#: four VAD heads -- 135 tensors against 131. The suffix names the
#: implementation it was published for, not a format PyTorch cannot read, and
#: the first benchmark of this model used the other one and so measured it with
#: the only feature worth having it for absent.
REPOSITORY = "kyutai/stt-1b-en_fr-candle"
REVISION = "095e38f6242006a93c2541149b181988397f5c7c"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    marker = _root() / ".marvi-revision"
    if args.check:
        raise SystemExit(
            0 if marker.is_file() and marker.read_text().strip() == REVISION else 1
        )
    from huggingface_hub import snapshot_download

    _root().mkdir(parents=True, exist_ok=True)
    snapshot_download(REPOSITORY, revision=REVISION, local_dir=_root())
    marker.write_text(REVISION + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
