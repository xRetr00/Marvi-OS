"""Shared Rich presentation for Marvi's interactive terminal surfaces."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import Any

MARVI_ART = (
    "\u2588\u2588\u2588\u2557   \u2588\u2588\u2588\u2557 \u2588\u2588\u2588\u2588\u2588\u2557 \u2588\u2588\u2588\u2588\u2588\u2588\u2557 \u2588\u2588\u2557   \u2588\u2588\u2557\u2588\u2588\u2557"
    "\n\u2588\u2588\u2588\u2588\u2557 \u2588\u2588\u2588\u2588\u2551\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u2588\u2588\u2551   \u2588\u2588\u2551\u2588\u2588\u2551"
    "\n\u2588\u2588\u2554\u2588\u2588\u2588\u2588\u2554\u2588\u2588\u2551\u2588\u2588\u2588\u2588\u2588\u2588\u2588\u2551\u2588\u2588\u2588\u2588\u2588\u2588\u2554\u255d\u2588\u2588\u2551   \u2588\u2588\u2551\u2588\u2588\u2551"
    "\n\u2588\u2588\u2551\u255a\u2588\u2588\u2554\u255d\u2588\u2588\u2551\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2551\u2588\u2588\u2554\u2550\u2550\u2588\u2588\u2557\u255a\u2588\u2588\u2557 \u2588\u2588\u2554\u255d\u2588\u2588\u2551"
    "\n\u2588\u2588\u2551 \u255a\u2550\u255d \u2588\u2588\u2551\u2588\u2588\u2551  \u2588\u2588\u2551\u2588\u2588\u2551  \u2588\u2588\u2551 \u255a\u2588\u2588\u2588\u2588\u2554\u255d \u2588\u2588\u2551"
    "\n\u255a\u2550\u255d     \u255a\u2550\u255d\u255a\u2550\u255d  \u255a\u2550\u255d\u255a\u2550\u255d  \u255a\u2550\u255d  \u255a\u2550\u2550\u2550\u255d  \u255a\u2550\u255d"
)

# U+FE0E requests text presentation so Windows terminals keep these Claude-style
# frames monochrome instead of selecting an emoji glyph with a colored backdrop.
MARVI_SPINNER_FRAMES = (
    "\u00b7\ufe0e",  # ·
    "\u2732\ufe0e",  # ✲
    "\u2735\ufe0e",  # ✵
    "\u2736\ufe0e",  # ✶
    "\u2737\ufe0e",  # ✷
    "\u2738\ufe0e",  # ✸
    "\u2739\ufe0e",  # ✹
    "\u273a\ufe0e",  # ✺
    "\u273b\ufe0e",  # ✻
    "\u273c\ufe0e",  # ✼
    "\u273d\ufe0e",  # ✽
    "\u273e\ufe0e",  # ✾
    "\u273f\ufe0e",  # ✿
)
LOADING_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789@#$%&*+-"
LOADING_FRAME_SECONDS = 0.035
LOADING_FRAMES_PER_CHAR = 3

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


@dataclass
class TextLoading:
    """A Claude-like left-to-right resolving text animation."""

    message: str
    started: float

    def frame(self, now: float | None = None) -> str:
        elapsed = (monotonic() if now is None else now) - self.started
        resolved = min(
            len(self.message),
            int(elapsed / LOADING_FRAME_SECONDS / LOADING_FRAMES_PER_CHAR),
        )
        frame = []
        for index, character in enumerate(self.message):
            if index < resolved or character == " ":
                frame.append(character)
            else:
                # Deterministic per frame keeps redraws stable while still
                # changing the unresolved characters at the requested cadence.
                slot = int(elapsed / LOADING_FRAME_SECONDS)
                frame.append(LOADING_CHARS[(index * 17 + slot) % len(LOADING_CHARS)])
        return "".join(frame)

    def spinner(self, now: float | None = None) -> str:
        elapsed = (monotonic() if now is None else now) - self.started
        slot = max(0, int(elapsed / LOADING_FRAME_SECONDS))
        return MARVI_SPINNER_FRAMES[slot % len(MARVI_SPINNER_FRAMES)]

    def render(self, now: float | None = None) -> str:
        return f"{self.spinner(now)} {self.frame(now)}"

    def __rich_console__(self, _console: Any, _options: Any) -> Iterator[Any]:
        from rich.text import Text

        yield Text(self.render(), style=CRAIL)


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
    """Show a left-to-right resolving Marvi status while an interactive task runs."""
    from rich.live import Live

    loading = TextLoading(message.upper(), monotonic())
    live = Live(loading, console=console, refresh_per_second=1 / LOADING_FRAME_SECONDS, transient=True)
    live.start()
    try:
        yield
    finally:
        from rich.text import Text

        live.update(Text(message.upper(), style=CRAIL), refresh=True)
        live.stop()
