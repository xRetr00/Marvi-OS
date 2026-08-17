"""`marvi` — the terminal front end.

This is not a second product. It calls the same functions the Gateway serves
over HTTP, in-process, so there is one implementation of setup and one of
Doctor. A PowerShell script would have been a *second* implementation, and the
second implementation is the one that drifts.

The reason it exists at all: **the desktop app cannot fix the desktop app.**
When Electron will not start or the Gateway will not bind, a button is
unreachable. That is not hypothetical — it is the failure that opened Phase 10.
It also matters that setup precedes the GUI on a fresh machine, and that a
multi-gigabyte download belongs somewhere it survives a window closing.

Everything here runs without a Gateway process. Nothing calls localhost.
"""

from __future__ import annotations

import argparse
import contextlib
import sys
from pathlib import Path

from . import breadcrumb, doctor, logs
from . import setup as setup_module
from .providers import all_profiles, configured_profiles
from .providers import config as provider_config

TICK = {"ok": "  ok  ", "warn": " warn ", "fail": " FAIL "}


def repo_root() -> Path:
    """The checkout this package lives in.

    Marvi ships as a git checkout for the updater's sake, so walking up from
    here is reliable in both a dev tree and an installed one.
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "config" / "components.json").exists():
            return parent
    return Path.cwd()


def gigabytes(count: int) -> str:
    return f"{count / 1024**3:.2f} GB" if count else "—"


# -- doctor --------------------------------------------------------------------


def cmd_doctor(args: argparse.Namespace) -> int:
    findings = doctor.run_checks()

    if args.fix:
        # Automatic remedies run regardless. Confirm-kind ones are shown first,
        # because "fix it" should not silently start a multi-gigabyte download
        # on someone's connection.
        consequential = [
            f for f in findings if f.remedy.kind == "confirm" and f.remedy.run is not None
        ]
        include_confirmed = True
        if consequential and not args.yes:
            print("These need your go-ahead:")
            for finding in consequential:
                print(f"  {finding.remedy.action} — {finding.detail}")
            print()
            include_confirmed = _confirm("Do all of that?")
            print()
        applied = doctor.heal(findings, include_confirmed=include_confirmed)
        for entry in applied:
            mark = "fixed" if entry["ok"] else "could not fix"
            print(f"  {mark}: {entry['check']} — {entry['outcome']}")
        if applied:
            print()
        findings = doctor.run_checks()

    for finding in findings:
        print(f"[{TICK[finding.status]}] {finding.area}/{finding.check}: {finding.detail}")
        if finding.status != "ok" and finding.remedy.kind != "none":
            print(f"          → {finding.remedy.action}")
            if finding.remedy.how:
                for line in finding.remedy.how.splitlines():
                    print(f"            {line}")

    counts = doctor.summary(findings)
    print(f"\n{counts['fail']} failing, {counts['warn']} warnings, {counts['ok']} ok")
    if counts["fail"] and not args.fix:
        print("Run `marvi doctor --fix` to apply what Marvi can do itself.")
    return 1 if counts["fail"] else 0


def cmd_diagnostics(_args: argparse.Namespace) -> int:
    # Already redacted: the log files it quotes were scrubbed on the way to disk.
    print(doctor.diagnostics())
    return 0


# -- setup ---------------------------------------------------------------------


def _selected(args: argparse.Namespace) -> list[setup_module.Component]:
    root = repo_root()
    everything = setup_module.load(root)
    if getattr(args, "essential", False):
        return [c for c in everything if c.essential]
    if not args.what:
        return everything
    chosen: list[setup_module.Component] = []
    for name in args.what:
        matches = [c for c in everything if c.name == name or name in c.needed_for]
        if not matches:
            print(f"unknown component or capability: {name}", file=sys.stderr)
        chosen.extend(matches)
    return chosen


def cmd_setup(args: argparse.Namespace) -> int:
    components = _selected(args)
    if not components:
        return 1

    plan = setup_module.plan(components)
    if not plan["install"]:
        print(f"Everything is already installed ({len(plan['already_installed'])} components).")
        return 0

    print("To install:")
    for entry in plan["install"]:
        print(f"  {entry['title']} — {gigabytes(entry['bytes'])}")
        if entry["why"]:
            print(f"      {entry['why']}")
    print(f"\nTotal download: {gigabytes(plan['bytes_total'])}")

    enough, detail = setup_module.disk_space_for(components)
    if not enough:
        # Better to refuse now than to fill the disk halfway through.
        print(f"Not enough disk space: {detail}", file=sys.stderr)
        return 1

    if args.dry_run:
        print("\nDry run; nothing downloaded.")
        return 0
    if not args.yes and not _confirm("Download now?"):
        return 0

    root = repo_root()
    failed = 0
    for component in components:
        outcome = setup_module.install(component, root, progress=_progress)
        _clear_line()
        mark = "ok" if outcome.ok else "FAILED"
        print(f"  {mark}: {component.title} — {outcome.detail}")
        failed += 0 if outcome.ok else 1
    return 1 if failed else 0


def _progress(component: str, path: str, done: int, total: int) -> None:
    share = f"{100 * done / total:5.1f}%" if total else f"{done / 1024**2:.0f} MB"
    name = path.rsplit("/", 1)[-1]
    sys.stdout.write(f"\r  {component}: {name} {share}   ")
    sys.stdout.flush()


def _clear_line() -> None:
    sys.stdout.write("\r" + " " * 70 + "\r")


def _confirm(question: str) -> bool:
    try:
        return input(f"{question} [y/N] ").strip().lower() in ("y", "yes")
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def cmd_models(args: argparse.Namespace) -> int:
    root = repo_root()
    components = setup_module.load(root)

    if args.action == "list":
        for component in components:
            state = setup_module.state_of(component, root)
            mark = "installed" if state["installed"] else state["detail"]
            print(f"{component.name:16} {component.kind:8} {mark:34} {gigabytes(component.bytes_total)}")
        return 0

    target = setup_module.get(root, args.name or "")
    if target is None:
        print(f"unknown component: {args.name}", file=sys.stderr)
        return 1

    if args.action == "verify":
        state = setup_module.state_of(target, root)
        print(f"{target.name}: {state['detail']}")
        for problem in state["problems"]:
            print(f"  {problem['file']}: {problem['reason']}")
        return 0 if state["installed"] else 1

    if args.action == "install":
        outcome = setup_module.install(target, root, progress=_progress, force=args.force)
        _clear_line()
        print(f"{target.name}: {outcome.detail}")
        return 0 if outcome.ok else 1

    if args.action == "remove":
        if not args.yes and not _confirm(f"Remove {target.title}?"):
            return 0
        outcome = setup_module.remove(target)
        print(f"{target.name}: {outcome.detail}")
        return 0 if outcome.ok else 1
    return 1


def cmd_gpu(args: argparse.Namespace) -> int:
    from .setup import hardware

    found = hardware.detect()
    print(found.detail)
    for gpu in found.gpus:
        mark = "usable" if gpu.usable else "not usable"
        memory = f" {gpu.memory_mb / 1024:.0f} GB" if gpu.memory_mb else ""
        print(f"  {gpu.name}{memory} — {mark} ({gpu.detail})")

    if args.use in ("gpu", "cpu"):
        hardware.remember(args.use == "gpu")
        print(f"Saved: models will use the {args.use.upper()}.")
        return 0

    answer = hardware.question(found)
    if not answer["ask"]:
        print(f"\n{answer['reason']} — using {'GPU' if answer['use_gpu'] else 'CPU'}.")
        return 0
    print(f"\n{answer['prompt']}")
    hardware.remember(_confirm("Use the GPU?"))
    return 0


def cmd_mcp(args: argparse.Namespace) -> int:
    from .setup import mcp

    if args.action == "list":
        rows = mcp.status()
        if not rows:
            print("No MCP servers configured.")
        for row in rows:
            state = "on " if row["enabled"] else "off"
            found = "" if row["on_path"] else "  (not on PATH)"
            print(f"[{state}] {row['name']:16} {row['command']}{found}")
        return 0

    if args.action == "add":
        if not args.name or not args.command:
            print("usage: marvi mcp add <name> -- <command> [args...]", file=sys.stderr)
            return 1
        prepared = mcp.prepare(args.name, args.command[0], args.command[1:])
        print(f"This will run:\n  {prepared['command']}")
        if prepared["resolved"]:
            print(f"  resolved to {prepared['resolved']}")
        for warning in prepared["warnings"]:
            print(f"  ! {warning}")
        # An MCP server runs code. The command is shown in full, every time,
        # before anything is written.
        print(f"\n{prepared['notice']}")
        if not args.yes and not _confirm("\nAdd it?"):
            return 0
        result = mcp.add(prepared["token"])
        print(result["detail"])
        return 0 if result["ok"] else 1

    if args.action == "remove":
        result = mcp.remove(args.name or "")
        print(result["detail"])
        return 0 if result["ok"] else 1

    if args.action == "test":
        servers = mcp.read()
        server = servers.get(args.name or "")
        if server is None:
            print(f"no server named {args.name}", file=sys.stderr)
            return 1
        print(f"starting {server.display()} ...")
        result = mcp.test(server)
        print(result["detail"])
        return 0 if result["ok"] else 1
    return 1


def cmd_skills(args: argparse.Namespace) -> int:
    from .setup import skills, store

    root = repo_root()
    if args.action == "list":
        for skill in skills.installed():
            print(f"{skill.name:24} {skill.description[:60]}")
        return 0

    if args.action == "browse":
        rows = store.catalogue(root)
        if not rows:
            print("No skills found. Check config/skill-sources.json.")
        for row in rows:
            mark = "installed" if row["installed"] else ""
            print(f"{row['name']:24} {mark:10} {row['description'][:52]}")
            print(f"{'':24} {row['repo']}/{row['path']}")
        return 0

    if args.action == "install":
        if not args.name:
            print("usage: marvi skills install <name>", file=sys.stderr)
            return 1
        match = next(
            (r for r in store.catalogue(root) if r["name"] == args.name), None
        )
        if match is None:
            print(f"no skill named {args.name} in any configured source", file=sys.stderr)
            return 1
        reviewed = store.review_remote(root, match["repo"], match["path"])
        if not reviewed.get("ok"):
            print(reviewed.get("detail", "could not fetch"), file=sys.stderr)
            return 1
        print(f"{reviewed['skill']['name']}: {reviewed['skill']['description'][:200]}")
        for warning in reviewed["warnings"]:
            print(f"  ! {warning}")
        # The body is instructions that will shape behaviour, so it is offered
        # rather than hidden behind a name and a description.
        if not args.yes and _confirm("\nShow the full instructions?"):
            print("\n" + reviewed["instructions"][:8000])
        if not args.yes and not _confirm("\nInstall it?"):
            return 0
        result = store.install_reviewed(reviewed["staged"])
        print(result["detail"])
        return 0 if result["ok"] else 1

    if args.action == "remove":
        result = skills.remove(args.name or "")
        print(result["detail"])
        return 0 if result["ok"] else 1
    return 1


def cmd_status(_args: argparse.Namespace) -> int:
    """Where this install has got to, and what would move it along."""
    from .setup import firstrun

    state = firstrun.status(repo_root())
    for step in state["steps"]:
        mark = "done" if step["done"] else ("NEEDED" if step["required"] else "optional")
        print(f"[{mark:8}] {step['title']}")
        if not step["done"]:
            print(f"           {step['why']}")
            print(f"           {step['action']}  ({step['detail']})")

    print()
    if not state["usable"]:
        print("Not usable yet: " + ", ".join(state["blocking"]))
    elif state["complete"]:
        print("Marvi is fully set up.")
    else:
        # Usable is not the same as complete, and saying so is what keeps a
        # first run short.
        print("Marvi is usable. The rest is optional.")
    return 0 if state["usable"] else 1


def cmd_paths(_args: argparse.Namespace) -> int:
    from . import paths

    for name, value in paths.describe().items():
        print(f"{name:10} {value}")
    return 0


# -- logs and providers ----------------------------------------------------------


def cmd_logs(args: argparse.Namespace) -> int:
    available = logs.available()
    if args.subsystem not in available and available:
        print(f"no {args.subsystem}.log — try one of: {', '.join(available)}", file=sys.stderr)
        return 1
    for line in logs.tail(args.subsystem, lines=args.lines):
        print(line)
    return 0


def cmd_providers(_args: argparse.Namespace) -> int:
    configured = {p.name for p in configured_profiles()}
    for profile in all_profiles():
        mark = "connected" if profile.name in configured else "—"
        print(f"{profile.name:18} {profile.access_path:6} {mark:12} {profile.model_for()}")
    saved = provider_config.visible()
    if saved:
        print("\nSaved settings (secrets masked):")
        for key, value in sorted(saved.items()):
            print(f"  {key} = {value}")
    return 0


def cmd_crashes(_args: argparse.Namespace) -> int:
    crumbs = breadcrumb.read_all()
    if not crumbs:
        print("No unclean exits recorded.")
        return 0
    for crumb in crumbs:
        print(f"{crumb.get('at', '?')}  {crumb.get('component', '?')}: {crumb.get('reason', '?')}")
    return 0


# -- entry point ------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="marvi", description="Marvi OS from the terminal."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    doctor_cmd = sub.add_parser("doctor", help="check everything and say what is wrong")
    doctor_cmd.add_argument(
        "--fix", action="store_true", help="apply what Marvi can fix itself"
    )
    doctor_cmd.add_argument(
        "--yes", "-y", action="store_true", help="do not ask before consequential fixes"
    )
    doctor_cmd.set_defaults(handler=cmd_doctor)

    diag = sub.add_parser("diagnostics", help="one redacted block for a bug report")
    diag.set_defaults(handler=cmd_diagnostics)

    setup_cmd = sub.add_parser("setup", help="install what is missing")
    setup_cmd.add_argument(
        "what", nargs="*", help="component or capability names; default is everything"
    )
    setup_cmd.add_argument("--yes", "-y", action="store_true", help="do not ask")
    setup_cmd.add_argument(
        "--essential",
        action="store_true",
        help="only what Marvi cannot start without; what the installer runs",
    )
    setup_cmd.add_argument("--dry-run", action="store_true", help="show the plan only")
    setup_cmd.set_defaults(handler=cmd_setup)

    models = sub.add_parser("models", help="list, verify, install or remove components")
    models.add_argument("action", choices=["list", "verify", "install", "remove"])
    models.add_argument("name", nargs="?")
    models.add_argument("--force", action="store_true", help="re-download even if verified")
    models.add_argument("--yes", "-y", action="store_true")
    models.set_defaults(handler=cmd_models)

    gpu = sub.add_parser("gpu", help="what Marvi found, and whether to use it")
    gpu.add_argument("use", nargs="?", choices=["gpu", "cpu"], help="set and remember")
    gpu.set_defaults(handler=cmd_gpu)

    mcp_cmd = sub.add_parser("mcp", help="MCP servers")
    mcp_cmd.add_argument("action", choices=["list", "add", "remove", "test"])
    mcp_cmd.add_argument("name", nargs="?")
    mcp_cmd.add_argument(
        "command", nargs="*", help="after --, the command and its arguments"
    )
    mcp_cmd.add_argument("--yes", "-y", action="store_true")
    mcp_cmd.set_defaults(handler=cmd_mcp)

    skills_cmd = sub.add_parser("skills", help="browse, install and remove skills")
    skills_cmd.add_argument("action", choices=["list", "browse", "install", "remove"])
    skills_cmd.add_argument("name", nargs="?")
    skills_cmd.add_argument("--yes", "-y", action="store_true")
    skills_cmd.set_defaults(handler=cmd_skills)

    status_cmd = sub.add_parser("status", help="what is left to set up")
    status_cmd.set_defaults(handler=cmd_status)

    paths_cmd = sub.add_parser("paths", help="where Marvi keeps everything")
    paths_cmd.set_defaults(handler=cmd_paths)

    logs_cmd = sub.add_parser("logs", help="tail a subsystem log")
    logs_cmd.add_argument("subsystem", nargs="?", default="errors")
    logs_cmd.add_argument("--lines", "-n", type=int, default=100)
    logs_cmd.set_defaults(handler=cmd_logs)

    providers = sub.add_parser("providers", help="what is connected")
    providers.set_defaults(handler=cmd_providers)

    crashes = sub.add_parser("crashes", help="unclean exits Marvi recorded")
    crashes.set_defaults(handler=cmd_crashes)

    return parser


def main(argv: list[str] | None = None) -> int:
    # The Windows console is cp1252 unless told otherwise, and both the log
    # lines this prints and Doctor's own remedies contain characters it cannot
    # encode. Without this, `marvi doctor` crashes on the first finding — on
    # the tool whose entire job is working when other things do not.
    for stream in (sys.stdout, sys.stderr):
        with contextlib.suppress(AttributeError, OSError):
            stream.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]

    args = build_parser().parse_args(argv)
    # Console output only: the CLI is often run *because* something is wrong,
    # and a command that cannot write its own log file should still work.
    provider_config.load_into_environ()
    try:
        return int(args.handler(args))
    except KeyboardInterrupt:
        print("\nStopped.")
        return 130


if __name__ == "__main__":
    sys.exit(main())
