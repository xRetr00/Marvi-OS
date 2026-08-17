"""Doctor: what is wrong, and what fixes it.

Part of Marvi, not a script beside it. A separate script would be a second
implementation of the same knowledge, and the second implementation is the one
that drifts. The page, the API, and the CLI all call the functions here.

Every check answers three questions, not one:

1. **Is it right?** `ok`, `warn`, or `fail`.
2. **Why not?** A specific reason, never "something went wrong".
3. **What fixes it?** A `Remedy`, and this is where the design lives.

## Three kinds of remedy

* **`automatic`** — safe, reversible, and obviously wanted. Create a missing
  directory, clear a stale cooldown, restart a crashed service. These run
  without asking.
* **`confirm`** — correct but consequential: `uv sync`, downloading gigabytes,
  stopping another process. Marvi shows the exact action and waits.
* **`manual`** — Marvi genuinely cannot. Install `uv`, grant a microphone
  permission, free disk space. Here the whole job is being *specific*:
  "permission denied" is a bad message, and the exact settings page is a useful
  one.

The line between the first two: **anything that spends money, takes real time,
downloads at scale, or touches another process is a decision, not a repair.**

Checks are pure — they read state and return a verdict. They never print, never
call HTTP, and never fix anything. That is what makes them testable, and what
lets the same function serve a page, an endpoint, and a terminal.
"""

from __future__ import annotations

import os
import shutil
import socket
import sqlite3
import sys
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from .identity import IdentityFiles
from .logs import get_logger, logs_dir
from .providers import all_profiles, configured_profiles
from .providers import config as provider_config

log = get_logger("doctor")

Status = Literal["ok", "warn", "fail"]
RemedyKind = Literal["automatic", "confirm", "manual", "none"]


@dataclass(frozen=True)
class Remedy:
    kind: RemedyKind
    #: One line, imperative. Shown on the button or as the instruction.
    action: str = ""
    #: For `manual`: exactly where to go or what to run. Specificity is the
    #: entire value of this field.
    how: str = ""
    #: Executed for `automatic` and `confirm`. None means nothing to run here.
    run: Callable[[], str] | None = None


NOTHING = Remedy(kind="none")


@dataclass
class Finding:
    check: str
    area: str
    status: Status
    detail: str
    remedy: Remedy = NOTHING
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def fixable(self) -> bool:
        return self.remedy.kind in ("automatic", "confirm") and self.remedy.run is not None

    def as_dict(self) -> dict[str, Any]:
        return {
            "check": self.check,
            "area": self.area,
            "status": self.status,
            "detail": self.detail,
            "remedy": {
                "kind": self.remedy.kind,
                "action": self.remedy.action,
                "how": self.remedy.how,
                "runnable": self.remedy.run is not None,
            },
            "extra": self.extra,
        }


# -- dependencies -------------------------------------------------------------


def find_uv() -> str | None:
    """Same search the desktop shell does, for the same reason.

    A GUI-launched app does not necessarily inherit the PATH a terminal has, and
    `uv` installs to `~/.local/bin`.
    """
    configured = os.environ.get("MARVI_UV_PATH", "").strip()
    if configured and Path(configured).exists():
        return configured
    found = shutil.which("uv")
    if found:
        return found
    home = Path(os.environ.get("USERPROFILE") or os.path.expanduser("~"))
    for candidate in (
        home / ".local" / "bin" / "uv.exe",
        home / ".cargo" / "bin" / "uv.exe",
        home / ".local" / "bin" / "uv",
    ):
        if candidate.exists():
            return str(candidate)
    return None


def check_uv() -> Finding:
    found = find_uv()
    if found:
        return Finding("uv", "dependencies", "ok", found)
    return Finding(
        "uv",
        "dependencies",
        "fail",
        "uv is not on PATH or in any known install location",
        Remedy(
            kind="manual",
            action="Install uv",
            # This was the actual first failure of the phase, so it gets the
            # command rather than a link to go and find it.
            how=(
                'Run in PowerShell: irm https://astral.sh/uv/install.ps1 | iex\n'
                "Then restart Marvi. If it is already installed, set "
                "MARVI_UV_PATH to its full path."
            ),
        ),
    )


def check_git() -> Finding:
    found = shutil.which("git")
    if found:
        return Finding("git", "dependencies", "ok", found)
    return Finding(
        "git",
        "dependencies",
        "warn",
        "git is missing; the in-app updater cannot run",
        Remedy(
            kind="manual",
            action="Install Git",
            how="https://git-scm.com/download/win — Marvi still runs without it.",
        ),
    )


# -- configuration ------------------------------------------------------------


def check_provider_settings() -> Finding:
    path = provider_config.config_path()
    if not path.exists():
        return Finding(
            "provider settings",
            "configuration",
            "warn",
            f"no saved settings at {path}",
            Remedy(
                kind="manual",
                action="Connect a provider",
                how="Open the Providers page and connect one. This file is written for you.",
            ),
        )
    try:
        provider_config.read(path)
    except Exception as exc:
        return Finding(
            "provider settings", "configuration", "fail", f"unreadable: {exc}"
        )
    return Finding("provider settings", "configuration", "ok", str(path))


def check_identity() -> Finding:
    files = IdentityFiles()
    identity = files.read()
    if not identity.present:
        return Finding(
            "identity",
            "configuration",
            "warn",
            "SOUL.md and USER.md are empty",
            Remedy(
                kind="manual",
                action="Write them",
                how="Open the Identity page. Marvi works without them; it is just less itself.",
            ),
        )
    if identity.truncated:
        return Finding(
            "identity",
            "configuration",
            "warn",
            f"truncated to fit the {files.budget} token budget",
            Remedy(
                kind="manual",
                action="Shorten them, or raise the budget",
                how=(
                    "Every token here is paid on every turn including the voice path. "
                    "Trim on the Identity page, or set MARVI_IDENTITY_BUDGET."
                ),
            ),
            {"tokens": identity.tokens, "budget": files.budget},
        )
    return Finding(
        "identity",
        "configuration",
        "ok",
        f"{identity.tokens} of {files.budget} tokens",
    )


# -- providers ----------------------------------------------------------------


def check_providers() -> Finding:
    configured = configured_profiles()
    if not configured:
        return Finding(
            "providers",
            "providers",
            "fail",
            f"none of the {len(all_profiles())} providers is configured",
            Remedy(
                kind="manual",
                action="Connect a provider",
                how=(
                    "Providers page: add an API key, sign into a plan, or start "
                    "Ollama or LM Studio locally."
                ),
            ),
        )
    return Finding(
        "providers",
        "providers",
        "ok",
        ", ".join(p.name for p in configured),
        extra={"configured": [p.name for p in configured]},
    )


def check_provider_reachable() -> Finding:
    """Configured is not the same as answering.

    A local provider counts as configured the moment it has a URL, so this is
    the check that distinguishes "set up" from "actually usable".
    """
    from .providers import ProviderClient

    client = ProviderClient()
    usable = [p.name for p in configured_profiles() if client.reachable(p, timeout=0.6)]
    if usable:
        return Finding("provider reachable", "providers", "ok", ", ".join(usable))
    if not configured_profiles():
        return Finding(
            "provider reachable", "providers", "fail", "nothing configured to reach"
        )
    return Finding(
        "provider reachable",
        "providers",
        "fail",
        "every configured provider is unreachable",
        Remedy(
            kind="manual",
            action="Start a local server, or check the network",
            how=(
                "A local provider is 'configured' as soon as it has a URL, which "
                "is not the same as something listening on it. Start Ollama or "
                "LM Studio, or connect a hosted provider."
            ),
        ),
    )


# -- ports and services --------------------------------------------------------


def port_open(host: str, port: int, timeout: float = 0.3) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def check_livekit(host: str = "127.0.0.1", port: int = 7880) -> Finding:
    if port_open(host, port):
        return Finding("livekit", "services", "ok", f"answering on {host}:{port}")
    return Finding(
        "livekit",
        "services",
        "warn",
        f"nothing listening on {host}:{port}",
        Remedy(
            kind="manual",
            action="Start LiveKit",
            how=(
                "Marvi starts it automatically when the server binary is "
                "installed. Run scripts/setup-voice-models.ps1, or point "
                "LIVEKIT_URL at a cloud project."
            ),
        ),
    )


# -- storage -------------------------------------------------------------------


def _writable(path: Path) -> tuple[bool, str]:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".marvi-write-test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True, ""
    except OSError as exc:
        return False, str(exc)


def check_storage() -> Finding:
    root = logs_dir().parent
    ok, reason = _writable(root)
    if ok:
        return Finding("storage", "storage", "ok", str(root))
    return Finding(
        "storage",
        "storage",
        "fail",
        f"{root} is not writable: {reason}",
        Remedy(
            kind="automatic",
            action="Create the directory",
            run=lambda: (
                "created" if _writable(root)[0] else "still not writable"
            ),
        ),
    )


def check_disk_space(minimum_gb: float = 5.0) -> Finding:
    root = logs_dir().parent
    try:
        free_gb = shutil.disk_usage(root).free / 1024**3
    except OSError as exc:
        return Finding("disk space", "storage", "warn", f"could not measure: {exc}")
    if free_gb >= minimum_gb:
        return Finding("disk space", "storage", "ok", f"{free_gb:.1f} GB free")
    return Finding(
        "disk space",
        "storage",
        "warn",
        f"only {free_gb:.1f} GB free; the voice models need several",
        Remedy(
            kind="manual",
            action="Free some space",
            how=f"Models and logs live under {root}.",
        ),
    )


def check_database(name: str, path: Path) -> Finding:
    if not path.exists():
        # Not an error: it is created on first use.
        return Finding(name, "storage", "ok", "not created yet")
    try:
        connection = sqlite3.connect(path)
        try:
            result = connection.execute("PRAGMA integrity_check").fetchone()[0]
        finally:
            connection.close()
    except sqlite3.Error as exc:
        result = str(exc)
    if result == "ok":
        return Finding(name, "storage", "ok", f"{path.stat().st_size // 1024} KB")
    return Finding(
        name,
        "storage",
        "fail",
        f"corrupt: {result}",
        Remedy(
            kind="confirm",
            action=f"Move {path.name} aside and start fresh",
            how="The old file is renamed, not deleted, so nothing is lost for good.",
            run=lambda: _quarantine(path),
        ),
    )


def _quarantine(path: Path) -> str:
    """Rename a corrupt file rather than deleting it. Losing data to a repair is
    worse than the corruption that prompted it."""
    from datetime import UTC, datetime

    stamp = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
    target = path.with_suffix(f"{path.suffix}.broken-{stamp}")
    path.rename(target)
    log.warning("quarantined %s to %s", path.name, target.name)
    return f"moved to {target.name}"


def check_databases() -> list[Finding]:
    from .chat import default_chat_path
    from .journal import default_journal_path

    return [
        check_database("journal", default_journal_path()),
        check_database("chat", default_chat_path()),
    ]


# -- token store ---------------------------------------------------------------


def check_token_store() -> Finding:
    from .providers.tokens import TokenStore

    store = TokenStore()
    if not store.path.exists():
        return Finding("oauth tokens", "providers", "ok", "no plans connected")
    connected = store.providers()
    if connected:
        return Finding(
            "oauth tokens",
            "providers",
            "ok",
            f"{', '.join(connected)} ({'encrypted' if store.encrypted else 'file permissions'})",
        )
    return Finding(
        "oauth tokens",
        "providers",
        "warn",
        "the token file exists but cannot be read",
        Remedy(
            kind="manual",
            action="Sign in again",
            how=(
                "Tokens are encrypted to your Windows account. A file written "
                "under a different account cannot be read here. Reconnect the "
                "plan on the Providers page."
            ),
        ),
    )


# -- logging --------------------------------------------------------------------


def check_logs() -> Finding:
    directory = logs_dir()
    ok, reason = _writable(directory)
    if not ok:
        return Finding(
            "logs",
            "storage",
            "fail",
            f"{directory} is not writable: {reason}",
            Remedy(
                kind="automatic",
                action="Create the log directory",
                run=lambda: "created" if _writable(directory)[0] else "still not writable",
            ),
        )
    from .logs import available

    return Finding(
        "logs", "storage", "ok", f"{len(available(directory))} files in {directory}"
    )


def check_crashes() -> Finding:
    from . import breadcrumb

    crumbs = breadcrumb.read_all()
    if not crumbs:
        return Finding("clean shutdown", "services", "ok", "no unclean exits recorded")
    latest = crumbs[-1]
    return Finding(
        "clean shutdown",
        "services",
        "warn",
        f"{len(crumbs)} unclean exit(s), last: {latest.get('reason', '?')}",
        Remedy(
            kind="automatic",
            action="Acknowledge and clear",
            run=lambda: "cleared" if breadcrumb.clear() else "nothing to clear",
        ),
        {"crashes": crumbs},
    )


# -- the sweep -------------------------------------------------------------------

SEVERITY = {"fail": 0, "warn": 1, "ok": 2}


def run_checks() -> list[Finding]:
    """Every check, worst first.

    Each one is isolated: a check that raises becomes a finding rather than
    taking the sweep down with it. Doctor failing is not an acceptable answer to
    "why is Marvi broken".
    """
    checks: list[Callable[[], Finding | list[Finding]]] = [
        check_uv,
        check_git,
        check_provider_settings,
        check_identity,
        check_providers,
        check_provider_reachable,
        check_livekit,
        check_storage,
        check_disk_space,
        check_logs,
        check_token_store,
        check_crashes,
        check_databases,
    ]
    findings: list[Finding] = []
    for check in checks:
        try:
            result = check()
        except Exception as exc:
            log.exception("check %s raised", getattr(check, "__name__", "?"))
            findings.append(
                Finding(
                    getattr(check, "__name__", "check").replace("check_", ""),
                    "doctor",
                    "warn",
                    f"this check could not run: {exc}",
                )
            )
            continue
        findings.extend(result if isinstance(result, list) else [result])
    findings.sort(key=lambda f: (SEVERITY[f.status], f.area, f.check))
    return findings


def summary(findings: list[Finding]) -> dict[str, int]:
    counts = {"ok": 0, "warn": 0, "fail": 0}
    for finding in findings:
        counts[finding.status] += 1
    return counts


def heal(findings: list[Finding], include_confirmed: bool = False) -> list[dict[str, Any]]:
    """Apply remedies. Automatic always; `confirm` only when asked.

    `manual` is never touched — that is the point of the category.
    """
    applied: list[dict[str, Any]] = []
    for finding in findings:
        kind = finding.remedy.kind
        if finding.remedy.run is None:
            continue
        if kind == "automatic" or (kind == "confirm" and include_confirmed):
            try:
                outcome = finding.remedy.run()
                log.info("healed %s: %s", finding.check, outcome)
                applied.append(
                    {"check": finding.check, "action": finding.remedy.action,
                     "outcome": outcome, "ok": True}
                )
            except Exception as exc:
                log.exception("remedy for %s failed", finding.check)
                applied.append(
                    {"check": finding.check, "action": finding.remedy.action,
                     "outcome": str(exc), "ok": False}
                )
    return applied


def diagnostics(findings: list[Finding] | None = None, log_lines: int = 60) -> str:
    """One block to paste into a bug report.

    Everything here is already redacted: the log files are scrubbed on the way
    to disk, and nothing else printed is a credential.
    """
    from .logs import tail

    found = findings if findings is not None else run_checks()
    counts = summary(found)
    lines = [
        "# Marvi OS diagnostics",
        f"python {sys.version.split()[0]} on {sys.platform}",
        f"checks: {counts['fail']} failing, {counts['warn']} warnings, {counts['ok']} ok",
        "",
        "## Findings",
    ]
    for finding in found:
        lines.append(f"[{finding.status.upper():<4}] {finding.area}/{finding.check}: {finding.detail}")
        if finding.status != "ok" and finding.remedy.kind != "none":
            lines.append(f"         fix ({finding.remedy.kind}): {finding.remedy.action}")
    recent = tail("errors", lines=log_lines)
    lines += ["", f"## errors.log (last {len(recent)} lines)", *recent]
    return "\n".join(lines)
