"""Shared Rich presentation for Marvi's interactive terminal surfaces."""

from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from collections.abc import Iterator
from typing import Any


MARVI_ART = (
    "\u2588\u2588\u2588\u2557   \u2588\u2588\u2588\u2557 \u2588\u2588\u2588\u2588\u2588\u2557 \u2588\u2588\u2588\u2588\u2588\u2588\u2557 \u2588\u2588\u2557   \u2588\u2588\u2557\u2588\u2588\u2557"
    "\n\u2588\u2588\u2588\u2588\u2557 \u2588\u2588\u2588\u2588\u2551\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2551   \u2588\u2588\u2551\u2588\u2588\u2551"
    "\n\u2588\u2588\u2554\u2588\u2588\u2588\u2588\u2554\u2588\u2588\u2551\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2551\u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d\u2588\u2588\u2551   \u2588\u2588\u2551\u2588\u2588\u2551"
    "\n\u2588\u2588\u2551\u255a\u2588\u2588\u2554\u255d\u2588\u2588\u2551\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2551\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u255a\u2588\u2588\u2557 \u2588\u2588\u2554\u255d\u2588\u2588\u2551"
    "\n\u2588\u2588\u2551 \u255a\u2550\u255d \u2588\u2588\u2551\u2588\u2588\u2551  \u2588\u2588\u2551\u2588\u2588\u2551  \u2588\u2588\u2551 \u255a\u2588\u2588\u2588\u2588\u2554\u255d \u2588\u2588\u2551"
    "\n\u255a\u2550\u255d     \u255a\u2550\u255d\u255a\u2550\u255d  \u255a\u2550\u255d\u255a\u2550\u255d  \u255a\u2550\u255d  \u255a\u2550\u2550\u2550\u255d  \u255a\u2550\u255d"
)

# ASCII-only frames avoid Windows emoji/font fallback, which can add a colored
# glyph background in some terminal profiles.
MARVI_SPINNER_FRAMES = ("-", "\\", "|", "/", "*", "+")

# Claude's Crail / Cloudy / Pampas palette, with semantic terminal colors.
CRAIL = "#c15f3c"
CLOUDY = "#b1ada1"
PAMPAS = "#f4f3ee"
SUCCESS = "#4daA72"
WARNING = "#d99a4a"
ERROR = "#d85b5b"
INFO = "#78a9c7"


def styled(text: str, color: str, *, bold: bool = False) -> str:
    weight = "bold " if bold else ""
    return f"[{weight}{color}]{text}[/{weight}{color}]"


def status_mark(status: str) -> str:
    colors = {"ok": SUCCESS, "warn": WARNING, "fail": ERROR}
    labels = {"ok": "OK", "warn": "WARN", "fail": "FAIL"}
    color = colors.get(status, CLOUDY)
    return styled(labels.get(status, status.upper()), color, bold=True)


def version(root: Path) -> str:
    """Read the single product version source used by the repository."""
    try:
        return (root / "VERSION").read_text(encoding="utf-8-sig").strip() or "unknown"
    except OSError:
        return "unknown"


def header(console: Any, root: Path, section: str) -> None:
    """Print the compact Marvi identity shared by interactive commands."""
    from rich.panel import Panel

    console.print(
        Panel.fit(
            f"{styled(MARVI_ART, CRAIL, bold=True)}\n"
            f"{styled('MARVI OS', CRAIL, bold=True)}  "
            f"{styled(f'v{version(root)}  |  {section}', CLOUDY)}",
            border_style=CRAIL,
            padding=(1, 2),
        )
    )


@contextmanager
def activity(console: Any, message: str) -> Iterator[None]:
    """Show a Claude-style Marvi spinner while an interactive task runs."""
    from rich.live import Live
    from rich.spinner import Spinner

    spinner = Spinner("dots", text=styled(message, CRAIL), style=CRAIL)
    spinner.frames = [str(frame) for frame in MARVI_SPINNER_FRAMES]
    spinner.interval = 80
    live = Live(spinner, console=console, refresh_per_second=12, transient=True)
    live.start()
    try:
        yield
    finally:
        live.stop()