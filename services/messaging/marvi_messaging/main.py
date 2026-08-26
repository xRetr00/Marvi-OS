"""Executable Marvi OS messaging application boundary."""

from __future__ import annotations

import argparse
import json
from collections.abc import Sequence

from .configuration import SECTIONS


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="marvi-messaging", description="Marvi OS messaging runtime")
    commands = parser.add_subparsers(dest="command", required=True)

    gateway = commands.add_parser("gateway", help="Messaging gateway lifecycle")
    gateway_commands = gateway.add_subparsers(dest="gateway_command", required=True)
    run = gateway_commands.add_parser("run", help="Run the bundled messaging gateway")
    run.add_argument("--replace", action="store_true")
    run.add_argument("--external-supervisor", action="store_true")
    run.add_argument("-v", "--verbose", action="count", default=0)
    run.add_argument("-q", "--quiet", action="store_true")

    gateway_commands.add_parser("stop", help="Request graceful gateway shutdown")
    commands.add_parser("health", help="Print Marvi messaging health as JSON")

    pairing = commands.add_parser("pairing", help="Manage messaging sender pairing")
    pairing_commands = pairing.add_subparsers(dest="pairing_command", required=True)
    pairing_commands.add_parser("list", help="Print pending pairing requests as JSON")
    approve = pairing_commands.add_parser("approve", help="Approve a pending sender")
    approve.add_argument("platform")
    approve.add_argument("credential", help="Marvi request id or one-time sender code")

    setup = commands.add_parser("setup", help="Configure Marvi messaging")
    setup.add_argument("section", choices=SECTIONS, nargs="?", default="gateway")
    setup.add_argument("--reset", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command == "setup":
        from .configuration import run_setup
        run_setup(args.section, reset=args.reset)
        return 0
    if args.command == "health":
        from .health import snapshot
        print(json.dumps(snapshot(), sort_keys=True))
        return 0
    if args.command == "pairing":
        from .pairing import approve, list_pending
        if args.pairing_command == "list":
            print(json.dumps(list_pending(), sort_keys=True))
            return 0
        result = approve(args.platform, args.credential)
        print(json.dumps(result, sort_keys=True))
        return 0 if result is not None else 1
    if args.gateway_command == "stop":
        from .lifecycle import request_shutdown
        return 0 if request_shutdown() else 1

    from .lifecycle import GatewayRunOptions, run_gateway
    return run_gateway(
        GatewayRunOptions(
            replace=args.replace,
            external_supervisor=args.external_supervisor,
            verbosity=None if args.quiet else args.verbose,
        )
    )


if __name__ == "__main__":
    raise SystemExit(main())
