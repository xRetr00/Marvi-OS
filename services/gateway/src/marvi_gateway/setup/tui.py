"""`marvi setup`, for a person rather than a script.

The CLI is fine at what it does and wrong for what it is usually used for.
Setting Marvi up is not one command, it is a handful of decisions -- which
models to fetch, whether the browser is worth its memory, which search backend
to use, and which keys those need -- and the CLI made you know the answers
before you could ask the question. `marvi setup --help` lists flags; it does not
tell you that web search is doing nothing because no backend is configured.

So this shows the state first and takes an action second. Everything it can do
the CLI can still do: any argument or flag goes down the old path unchanged, so
every scripted invocation keeps working, and only a bare interactive `marvi
setup` opens this.

Rendered with `rich`, which the environment already has. Not a full-screen app
framework -- this is a menu that prints, not something to live in, and a
setup tool that captures the terminal is harder to read back than one that
leaves its output in the scrollback.
"""

from __future__ import annotations

import os
import sys
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..providers import config as provider_config

#: Settings that switch a capability on, or give it what it needs to work.
#:
#: Kept here rather than discovered, because the point of the screen is to show
#: what is *not* set -- and something unset cannot be discovered by looking at
#: the environment. A capability missing from this list is invisible, which is
#: the failure this whole screen exists to fix.


@dataclass(frozen=True)
class Setting:
    name: str
    label: str
    detail: str
    secret: bool = False
    boolean: bool = False
    #: What the code does when this is unset.
    #:
    #: Without it the screen reported every default as a gap: announcements are
    #: on unless you turn them off, and the row said "not set", which reads as
    #: something still to do. And a switch that was set to *off* counted as
    #: configured, so browser tools showed ready while being disabled -- the
    #: exact two ways a status screen can be worse than no status screen.
    default: str = ""


@dataclass(frozen=True)
class Capability:
    key: str
    title: str
    why: str
    settings: tuple[Setting, ...]
    #: Satisfied when any one of its settings is present, rather than all: web
    #: search needs a backend, not every backend.
    any_of: bool = False


CAPABILITIES: tuple[Capability, ...] = (
    Capability(
        key="web",
        title="Web search and reading",
        why="Marvi can look things up rather than guessing from training data.",
        any_of=True,
        settings=(
            Setting(
                "SEARXNG_URL",
                "SearXNG URL",
                "A SearXNG instance you run or trust. No key, no quota.",
            ),
            Setting(
                "BRAVE_SEARCH_API_KEY",
                "Brave Search API key",
                "Hosted search. Free tier is enough for personal use.",
                secret=True,
            ),
        ),
    ),
    Capability(
        key="browser",
        title="Browser tools",
        why=(
            "Lets Marvi open pages that need a real browser. Off by default: a "
            "headless browser is a real memory cost, held for the session."
        ),
        settings=(
            Setting(
                "MARVI_BROWSER",
                "Enable browser tools",
                "Needs the Playwright browser installed (marvi setup browser).",
                boolean=True,
                default="false",
            ),
        ),
    ),
    Capability(
        key="announce",
        title="Speaking unprompted",
        why="Whether Marvi may start a conversation rather than only answering.",
        settings=(
            Setting(
                "MARVI_ANNOUNCE",
                "Allow announcements",
                "On unless you turn it off.",
                boolean=True,
                default="true",
            ),
        ),
    ),
    Capability(
        key="wake",
        title="Wake word",
        why="Saying 'Marvi' joins hands-free, the same as pressing Join.",
        settings=(
            Setting(
                "MARVI_WAKE_THRESHOLD",
                "Sensitivity",
                "0.35 catches you sooner; 0.7 almost never fires by accident.",
                default="0.5",
            ),
        ),
    ),
)


def _effective(setting: Setting) -> str:
    """What the code will actually see, configured or not."""
    return os.environ.get(setting.name, "").strip() or setting.default


def _on(value: str) -> bool:
    return value.strip().lower() in ("1", "true", "on", "yes")


def _satisfied(setting: Setting) -> bool:
    """Whether this setting is doing something, rather than merely being set."""
    value = _effective(setting)
    if not value:
        return False
    return _on(value) if setting.boolean else True


def _shown(setting: Setting) -> str:
    raw = os.environ.get(setting.name, "").strip()
    if not raw:
        if not setting.default:
            return "[dim]not set[/dim]"
        word = ("on" if _on(setting.default) else "off") if setting.boolean else setting.default
        return f"[dim]{word} (default)[/dim]"
    if setting.secret:
        return f"[green]{provider_config.mask(raw)}[/green]"
    if setting.boolean:
        return "[green]on[/green]" if _on(raw) else "[yellow]off[/yellow]"
    return f"[green]{raw}[/green]"


def _ready(capability: Capability) -> bool:
    present = [_satisfied(s) for s in capability.settings]
    return any(present) if capability.any_of else all(present)


def available() -> bool:
    """Whether a TUI makes sense here at all.

    Not on a pipe, not in CI, not when something is reading our output: a menu
    that asks questions nobody can answer hangs a build. Those get the CLI.
    """
    try:
        return sys.stdin.isatty() and sys.stdout.isatty()
    except Exception:  # pragma: no cover - depends on how it was launched
        return False


def run(
    *,
    components: list[Any],
    plan: Callable[[list[Any]], dict[str, Any]],
    install: Callable[..., Any],
    root: Any,
    console: Any = None,
) -> int:
    """Show what is set up and offer to change it. Returns an exit code.

    Dependencies are passed in rather than imported so this module stays
    testable without a real installation on disk -- the components, the plan and
    the installer are the parts that touch the network and the filesystem.
    """
    from rich.console import Console
    from rich.panel import Panel
    from rich.prompt import Prompt

    console = console or Console()
    provider_config.load_into_environ()

    while True:
        console.print()
        console.print(
            Panel.fit(
                "[bold]Marvi setup[/bold]\n"
                "[dim]Everything here is also a command; run `marvi setup --help`.[/dim]",
                border_style="cyan",
            )
        )

        current = plan(components)
        missing = current["install"]
        console.print(_components_table(components, missing))
        console.print(_capabilities_table())

        choices = ["c", "t", "q"]
        console.print(
            "\n[bold]c[/bold] install components   "
            "[bold]t[/bold] tools and keys   "
            "[bold]q[/bold] quit"
        )
        answer = Prompt.ask("Choose", choices=choices, default="q", console=console)
        if answer == "q":
            return 0
        if answer == "c":
            _install_components(console, components, current, install, root)
        else:
            _edit_capabilities(console)


def _components_table(components: list[Any], missing: list[Any]) -> Any:
    from rich.table import Table

    names = {entry["title"] for entry in missing}
    table = Table(title="Components", title_justify="left", header_style="bold")
    table.add_column("")
    table.add_column("Component")
    table.add_column("Size", justify="right")
    table.add_column("Needed for")
    for component in components:
        absent = component.title in names
        table.add_row(
            "[yellow]..[/yellow]" if absent else "[green]ok[/green]",
            component.title,
            _gigabytes(getattr(component, "bytes", 0) or 0),
            ", ".join(getattr(component, "needed_for", ()) or ()) or "[dim]-[/dim]",
        )
    return table


def _capabilities_table() -> Any:
    from rich.table import Table

    table = Table(title="Tools", title_justify="left", header_style="bold")
    table.add_column("")
    table.add_column("Capability")
    table.add_column("Setting")
    table.add_column("Value")
    for capability in CAPABILITIES:
        mark = "[green]ok[/green]" if _ready(capability) else "[yellow]..[/yellow]"
        for index, setting in enumerate(capability.settings):
            table.add_row(
                mark if index == 0 else "",
                capability.title if index == 0 else "",
                setting.label,
                _shown(setting),
            )
    return table


def _install_components(
    console: Any, components: list[Any], current: dict[str, Any], install: Any, root: Any
) -> None:
    from rich.progress import BarColumn, Progress, TextColumn, TimeRemainingColumn
    from rich.prompt import Confirm

    if not current["install"]:
        console.print("[green]Everything is already installed.[/green]")
        return

    total = _gigabytes(current["bytes_total"])
    console.print(f"\n{len(current['install'])} to install, {total} to download.")
    if not Confirm.ask("Download now?", default=False, console=console):
        return

    wanted = {entry["title"] for entry in current["install"]}
    todo = [c for c in components if c.title in wanted]
    failed = 0
    with Progress(
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.percentage:>3.0f}%"),
        TimeRemainingColumn(),
        console=console,
    ) as progress:
        for component in todo:
            task = progress.add_task(component.title, total=100)

            def report(_name: str, _path: str, done: int, size: int, task=task) -> None:
                progress.update(task, completed=(100 * done / size) if size else 0)

            outcome = install(component, root, progress=report)
            progress.update(task, completed=100)
            if not outcome.ok:
                failed += 1
                console.print(f"  [red]failed[/red]: {component.title} - {outcome.detail}")
    if failed:
        console.print(f"[red]{failed} component(s) failed.[/red]")


def _edit_capabilities(console: Any) -> None:
    """Set what a capability needs, and write it where the app will read it."""
    from rich.prompt import Prompt

    keys = [c.key for c in CAPABILITIES]
    console.print("\n" + "   ".join(f"[bold]{c.key}[/bold] {c.title}" for c in CAPABILITIES))
    chosen = Prompt.ask("Which", choices=[*keys, "back"], default="back", console=console)
    if chosen == "back":
        return

    capability = next(c for c in CAPABILITIES if c.key == chosen)
    console.print(f"\n[dim]{capability.why}[/dim]")
    changes: dict[str, str] = {}
    for setting in capability.settings:
        console.print(f"\n[bold]{setting.label}[/bold]  [dim]{setting.detail}[/dim]")
        console.print(f"  currently: {_shown(setting)}")
        if setting.boolean:
            answer = Prompt.ask(
                "  on, off, or leave", choices=["on", "off", ""], default="", console=console
            )
            if answer:
                changes[setting.name] = "true" if answer == "on" else "false"
            continue
        answer = Prompt.ask(
            "  value (blank to leave)",
            default="",
            password=setting.secret,
            console=console,
        )
        if answer.strip():
            changes[setting.name] = answer.strip()

    if not changes:
        console.print("[dim]Nothing changed.[/dim]")
        return
    # The same file the Providers page writes, so a key set here shows up there
    # and survives a restart. Secrets never come back out of it in the clear.
    provider_config.update(changes)
    for name, value in changes.items():
        os.environ[name] = value
    console.print(f"[green]Saved {len(changes)} setting(s).[/green]")
    console.print("[dim]Restart Marvi for a running Gateway to pick them up.[/dim]")


def _gigabytes(size: int) -> str:
    if not size:
        return "[dim]-[/dim]"
    if size < 1024**3:
        return f"{size / 1024**2:.0f} MB"
    return f"{size / 1024**3:.1f} GB"
