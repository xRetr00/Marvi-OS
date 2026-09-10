"""Shared Rich presentation for Marvi's interactive terminal surfaces."""

from __future__ import annotations

from pathlib import Path
from typing import Any


MARVI_ART = (
    "\u2584\u2584\u2584      \u2584\u2584\u2584   \u2584\u2584\u2584\u2584   \u2584\u2584\u2584\u2584\u2584\u2584\u2584   \u2584\u2584\u2584\u2584  \u2584\u2584\u2584\u2584 \u2584\u2584\u2584\u2584\u2584 "
    "\n\u2588\u2588\u2588\u2588\u2584  \u2584\u2588\u2588\u2588\u2588 \u2584\u2588\u2588\u▀\u▀\u2588\u2588\u2584 \u2588\u2588\u2588\u▀\u▀\u2588\u2588\u2588\u2584 \u2580\u2588\u2588\u2588  \u2588\u2588\u2588\u▀  \u2588\u2588\u2588  "
    "\n\u2588\u2588\u2588\u▀\u2588\u2588\u2588\u▀\u2588\u2588\u2588 \u2588\u2588\u2588  \u2588\u2588\u2588 \u2588\u2588\u2588\u2584\u2584\u2588\u2588\u2588\u▀  \u2588\u2588\u2588  \u2588\u2588\u2588   \u2588\u2588\u2588  "
    "\n\u2588\u2588\u2588  \u2580\u2580  \u2588\u2588\u2588 \u2588\u2588\u2588\u▀\u▀\u2588\u2588\u2588 \u2588\u2588\u2588\u▀\u▀\u2588\u2588\u2584 \u2588\u2588\u2588\u2584\u2584\u2588\u2588\u2588   \u2588\u2588\u2588   \u2588\u2588\u2588  "
    "\n\u2588\u2588\u2588      \u2588\u2588\u2588 \u2588\u2588\u2588  \u2588\u2588\u2588 \u2588\u2588\u2588  \u2580\u2588\u2588\u2588  \u2580\u2588\u2588\u2588\u2588\u2580   \u2588\u2588\u2588\u▀   \u2584\u2588\u2588\u2588\u2584"
)


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
            f"[bold bright_white]{MARVI_ART}[/bold bright_white]\n"
            f"[bold cyan]MARVI OS[/bold cyan]  [dim]v{version(root)}  |  {section}[/dim]",
            border_style="blue",
            padding=(1, 2),
        )
    )