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

MARVI_SPINNER_FRAMES = ("\u00b7", "\u2732", "\u2733", "\u2736", "\u273b", "\u273d")


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
            f"[bold #c15f3c]{MARVI_ART}[/bold #c15f3c]\n"
            f"[bold cyan]MARVI OS[/bold cyan]  [dim]v{version(root)}  |  {section}[/dim]",
            border_style="blue",
            padding=(1, 2),
        )
    )


@contextmanager
def activity(console: Any, message: str) -> Iterator[None]:
    """Show a Claude-style Marvi spinner while an interactive task runs."""
    from rich.live import Live
    from rich.spinner import Spinner

    spinner = Spinner("dots", text=f"[cyan]{message}[/cyan]", style="cyan")
    spinner.frames = [str(frame) for frame in MARVI_SPINNER_FRAMES]
    spinner.interval = 80
    live = Live(spinner, console=console, refresh_per_second=12, transient=True)
    live.start()
    try:
        yield
    finally:
        live.stop()