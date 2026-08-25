"""Setup-owned PocketTTS model and default voice preparation."""

from __future__ import annotations

import argparse
import json
from importlib.metadata import PackageNotFoundError, version

from ..announce import Announcer, pocket_cache_dir


def marker_path():
    return pocket_cache_dir().parent / "ready.json"


def installed() -> bool:
    marker = marker_path()
    if not marker.is_file() or not pocket_cache_dir().is_dir():
        return False
    try:
        state = json.loads(marker.read_text(encoding="utf-8"))
        package = version("pocket-tts")
    except (OSError, ValueError, PackageNotFoundError):
        return False
    return state.get("package") == package and bool(state.get("voice"))


def install() -> dict[str, object]:
    announcer = Announcer()
    result = announcer.prepare()
    marker = marker_path()
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps(
            {
                "package": version("pocket-tts"),
                "voice": result["voice"],
                "cache": str(pocket_cache_dir()),
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prepare PocketTTS for one-shot speech.")
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    if args.check:
        return 0 if installed() else 1
    print(json.dumps(install()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
