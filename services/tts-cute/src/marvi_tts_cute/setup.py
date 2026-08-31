from __future__ import annotations

import argparse

from .host import _root

REVISION = "6f84092f441295c415019193424033c93c6aee68"


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
    snapshot_download("OPPOer/CuteTTS-distill", revision=REVISION, local_dir=_root())
    marker.write_text(REVISION + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
