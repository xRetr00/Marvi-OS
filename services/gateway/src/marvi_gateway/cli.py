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

from . import breadcrumb, doctor, logs, plugins
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


# -- schedules -----------------------------------------------------------------


def cmd_cron(args: argparse.Namespace) -> int:
    """Reminders, from a shell.

    The CLI matters here for the same reason it does everywhere else in Marvi:
    when the app will not start, the reminder you set for tomorrow morning
    should still be readable and cancellable.
    """
    from .schedule import ScheduleError, Scheduler, ScheduleStore

    store = ScheduleStore()
    try:
        if args.action == "list":
            rows = store.list()
            if not rows:
                print("No reminders. Add one with:")
                print('  marvi cron add "wake up" --at 07:30 --message "Time to get up" --insist')
                return 0
            for row in rows:
                state = "on " if row.enabled else "off"
                insist = " insists" if row.insist else ""
                when = f"every {row.expression}m" if row.kind == "interval" else row.expression
                print(f"[{row.id:3}] {state} {row.name:24} {row.action:14} {when}{insist}")
                if row.message:
                    print(f"           {row.message}")
                if row.last_error:
                    print(f"           last error: {row.last_error}")
                elif row.last_run:
                    print(f"           last run: {row.last_run}")
            return 0

        if args.action == "add":
            if not args.name or not args.at:
                print('usage: marvi cron add "<name>" --at <when>', file=sys.stderr)
                return 1
            expression, kind = args.at.strip(), "cron"
            if expression.isdigit():
                kind = "interval"
            elif ":" in expression and len(expression.split(":")) == 2:
                hour, _, minute = expression.partition(":")
                try:
                    expression = f"{int(minute)} {int(hour)} * * *"
                except ValueError:
                    print(f"{args.at!r} is not a time Marvi understands", file=sys.stderr)
                    return 1
            made = store.add(
                args.name, args.what, kind, expression, args.message, insist=args.insist
            )
            print(f"added [{made.id}] {made.name} at {made.expression}")
            if made.insist:
                print("  it will speak during quiet hours and while the room is asleep")
            return 0

        if not args.name:
            print("which reminder? try `marvi cron list`", file=sys.stderr)
            return 1
        try:
            schedule_id = int(args.name)
        except ValueError:
            print(f"{args.name!r} is not an id; `marvi cron list` shows them", file=sys.stderr)
            return 1

        if args.action == "remove":
            print("removed" if store.remove(schedule_id) else "no such reminder")
            return 0
        if args.action in ("enable", "disable"):
            row = store.set_enabled(schedule_id, args.action == "enable")
            print(f"{row.name} is {'on' if row.enabled else 'off'}")
            return 0
        if args.action == "run":
            # Fires it now, through the same path the scheduler uses, which is
            # the only honest way to test that a reminder works.
            from .journal import EventJournal

            journal = EventJournal()
            try:
                outcome = Scheduler(store, journal=journal).fire(schedule_id)
            finally:
                journal.close()
            print(outcome.get("detail", "done"))
            return 0 if outcome.get("ok") else 1
        return 1
    except ScheduleError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    finally:
        store.close()


# -- plugins -------------------------------------------------------------------


def cmd_plugin(args: argparse.Namespace) -> int:
    """Install, update and inspect desktop plugins.

    A plugin is a backend Marvi runs, not a prompt (`marvi skills`) and not
    someone else's tool process (`marvi mcp`). Installing one runs its code in
    the Gateway, which is why it is a deliberate command and not something setup
    does quietly.
    """
    root = repo_root()

    if args.action == "list":
        rows = plugins.status(root)
        if not rows:
            print("No plugins are declared in config/plugin-sources.json.")
            return 0
        for row in rows:
            mark = "installed" if row["installed"] else "not installed"
            version = f" v{row['version']}" if row["version"] else ""
            commit = f" @{row['commit']}" if row["commit"] else ""
            print(f"{row['name']:14} {mark:14}{version}{commit}")
            if row["why"]:
                print(f"               {row['why']}")
            if not row["supported"]:
                print(f"               {row['detail']}")
            if row["tools"]:
                print(f"               tools: {', '.join(row['tools'])}")
        return 0

    if not args.name:
        print("which plugin? try `marvi plugin list`", file=sys.stderr)
        return 1

    if args.action == "install":
        source = plugins.source_for(root, args.name)
        if source is None:
            print(f"unknown plugin: {args.name}", file=sys.stderr)
            return 1
        # A plugin's code runs inside the Gateway and its dependencies land in
        # the Gateway's environment. That is a trust decision, so it is asked.
        print(f"{source.title} — {source.repo} ({source.ref})")
        if source.why:
            print(f"  {source.why}")
        print("  Its code runs inside Marvi and its dependencies install into Marvi.")
        if not args.yes and not _confirm("Install it?"):
            return 0
        try:
            print(plugins.install(source, root))
        except plugins.PluginError as exc:
            print(f"install failed: {exc}", file=sys.stderr)
            return 1
        return 0

    if args.action == "update":
        try:
            print(plugins.update(args.name, root))
        except plugins.PluginError as exc:
            print(f"update failed: {exc}", file=sys.stderr)
            return 1
        return 0

    if args.action == "remove":
        if not args.yes and not _confirm(f"Remove the {args.name} plugin?"):
            return 0
        try:
            print(plugins.remove(args.name))
        except plugins.PluginError as exc:
            print(f"remove failed: {exc}", file=sys.stderr)
            return 1
        return 0
    return 1


# -- setup ---------------------------------------------------------------------


def _wants_tui(args: argparse.Namespace) -> bool:
    """Only the bare interactive form. Everything else is the CLI it was."""
    if args.what or args.yes or args.essential or args.dry_run:
        return False
    from .setup import tui

    return tui.available()


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
    """Install what is missing.

    A bare `marvi setup` from a terminal opens the screen; anything else --
    named components, `--yes`, `--essential`, `--dry-run`, a pipe, CI -- takes
    the same path it always did. So no scripted invocation changes, and the one
    a person types stops requiring them to know the answers first.
    """
    if _wants_tui(args):
        from .setup import tui

        return tui.run(
            components=setup_module.load(repo_root()),
            plan=setup_module.plan,
            install=setup_module.install,
            root=repo_root(),
        )
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

    if args.action == "prune":
        # Model directories nothing loads any more. Named separately from
        # `remove` because there is no component to name: these are left over
        # from a version that had one, and `remove` takes a component name.
        import shutil

        from . import upgrade

        leftovers = upgrade.reclaimable()
        if not leftovers:
            print("Nothing to reclaim.")
            return 0
        for entry in leftovers:
            print(f"  {entry.path}  {entry.gigabytes:.1f} GB — {entry.why}")
        total = sum(entry.gigabytes for entry in leftovers)
        if not args.yes and not _confirm(f"Delete {total:.1f} GB?"):
            return 0
        for entry in leftovers:
            try:
                shutil.rmtree(entry.path)
                print(f"  removed {entry.path.name}")
            except OSError as exc:
                print(f"  could not remove {entry.path}: {exc}", file=sys.stderr)
                return 1
        return 0

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
    models.add_argument(
        "action", choices=["list", "verify", "install", "remove", "prune"]
    )
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

    plugin_cmd = sub.add_parser("plugin", help="desktop plugins (the room engine and friends)")
    plugin_cmd.add_argument("action", choices=["list", "install", "update", "remove"])
    plugin_cmd.add_argument("name", nargs="?")
    plugin_cmd.add_argument("--yes", "-y", action="store_true")
    plugin_cmd.set_defaults(handler=cmd_plugin)

    cron_cmd = sub.add_parser("cron", help="reminders and scheduled checks")
    cron_cmd.add_argument("action", choices=["list", "add", "remove", "enable", "disable", "run"])
    cron_cmd.add_argument("name", nargs="?", help="a name to add, or an id for the rest")
    cron_cmd.add_argument("--at", help='when: "07:30", a cron expression, or minutes')
    cron_cmd.add_argument("--message", default="", help="what Marvi should say")
    cron_cmd.add_argument("--action", dest="what", default="remind", help="what to run")
    cron_cmd.add_argument(
        "--insist",
        action="store_true",
        help="speak even during quiet hours and while the room is asleep",
    )
    cron_cmd.set_defaults(handler=cmd_cron)

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
