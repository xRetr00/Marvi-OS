from __future__ import annotations

import asyncio
import os
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch


SERVICE_ROOT = Path(__file__).resolve().parents[1]
if str(SERVICE_ROOT) not in sys.path:
    sys.path.insert(0, str(SERVICE_ROOT))

from marvi_messaging import main
from marvi_messaging.lifecycle import GatewayRunOptions, run_gateway


class MarviMessagingRuntimeTests(unittest.TestCase):
    def test_parser_exposes_only_marvi_owned_commands(self):
        parser = main.build_parser()
        self.assertEqual(parser.prog, "marvi-messaging")
        with self.assertRaises(SystemExit) as raised:
            parser.parse_args(["gateway", "run", "--help"])
        self.assertEqual(raised.exception.code, 0)

    def test_lifecycle_calls_reusable_gateway_api_without_cli_dispatch(self):
        calls: dict[str, object] = {}

        async def start_gateway(*, replace=False, verbosity=0):
            calls.update(replace=replace, verbosity=verbosity)
            return True

        def finish(code):
            calls["exit"] = code

        gateway_package = types.ModuleType("gateway")
        gateway_run = types.ModuleType("gateway.run")
        gateway_run.start_gateway = start_gateway
        gateway_run._exit_after_graceful_shutdown = finish

        with (
            patch("marvi_messaging.lifecycle.activate"),
            patch.dict(sys.modules, {"gateway": gateway_package, "gateway.run": gateway_run}),
        ):
            result = run_gateway(
                GatewayRunOptions(replace=True, verbosity=2, external_supervisor=True)
            )

        self.assertEqual(result, 0)
        self.assertEqual(calls, {"replace": True, "verbosity": 2, "exit": 0})

    def test_marvi_environment_is_bridged_only_inside_vendor_adapter(self):
        from marvi_messaging._vendor import activate

        vendor = Path(__file__).resolve().parents[3] / "vendor" / "marvi-agent"
        with tempfile.TemporaryDirectory() as home, patch.dict(
            os.environ,
            {
                "MARVI_MESSAGING_HOME": home,
                "MARVI_MESSAGING_VENDOR_ROOT": str(vendor),
                "MARVI_MESSAGING_EXTERNAL_SUPERVISOR": "1",
            },
            clear=False,
        ):
            activate(managed=True)
            self.assertEqual(os.environ["HERMES_HOME"], home)
            self.assertEqual(os.environ["HERMES_MANAGED"], "marvi-os")
            self.assertEqual(os.environ["AI_AGENT"], "marvi-os-messaging")
            from gateway.run import _resolve_hermes_bin
            self.assertIsNone(_resolve_hermes_bin())
            from gateway.slash_commands import GatewaySlashCommandsMixin
            result = asyncio.run(GatewaySlashCommandsMixin._handle_update_command(object(), None))
            self.assertEqual(result, "Messaging updates are installed and managed by Marvi OS.")

    def test_owned_runtime_never_imports_hermes_cli_main(self):
        runtime = SERVICE_ROOT / "marvi_messaging"
        sources = "\n".join(path.read_text(encoding="utf-8") for path in runtime.glob("*.py"))
        self.assertNotIn("hermes_cli.main", sources)

    def test_gateway_setup_configures_adapters_without_service_install(self):
        from marvi_messaging.configuration import run_setup

        calls: list[str] = []
        cli_package = types.ModuleType("hermes_cli")
        config_module = types.ModuleType("hermes_cli.config")
        config_module.DEFAULT_CONFIG = {}
        config_module.ensure_hermes_home = lambda: calls.append("home")
        config_module.load_config = lambda: {}
        config_module.save_config = lambda config: calls.append("save")
        setup_module = types.ModuleType("hermes_cli.setup")
        setup_module.SETUP_SECTIONS = [
            ("gateway", "Messaging Platforms", lambda config: calls.append("upstream-service-setup"))
        ]
        setup_module.prompt_checklist = lambda prompt, choices, selected: [0]
        gateway_module = types.ModuleType("hermes_cli.gateway")
        gateway_module._all_platforms = lambda: [{"emoji": "#", "label": "Test"}]
        gateway_module._platform_status = lambda platform: "not configured"
        gateway_module._configure_platform = lambda platform: calls.append("adapter")

        with (
            patch("marvi_messaging.configuration.activate"),
            patch.dict(
                sys.modules,
                {
                    "hermes_cli": cli_package,
                    "hermes_cli.config": config_module,
                    "hermes_cli.setup": setup_module,
                    "hermes_cli.gateway": gateway_module,
                },
            ),
        ):
            run_setup("gateway")

        self.assertEqual(calls, ["home", "adapter", "save"])

    def test_pairing_approves_server_side_request_without_exposing_code(self):
        from marvi_messaging.pairing import approve

        calls: list[tuple[str, str]] = []

        class PairingStore:
            @staticmethod
            def looks_like_request_id(value):
                return value == "0123456789abcdef"

            def approve_request(self, platform, request_id):
                calls.append((platform, request_id))
                return {"user_id": "42", "user_name": "Owner"}

            def approve_code(self, platform, code):
                raise AssertionError("the renderer-owned path must not expose pairing codes")

        gateway_package = types.ModuleType("gateway")
        pairing_module = types.ModuleType("gateway.pairing")
        pairing_module.PairingStore = PairingStore
        with (
            patch("marvi_messaging.pairing.activate"),
            patch.dict(sys.modules, {"gateway": gateway_package, "gateway.pairing": pairing_module}),
        ):
            result = approve("Telegram", "0123456789abcdef")

        self.assertEqual(result, {"user_id": "42", "user_name": "Owner"})
        self.assertEqual(calls, [("telegram", "0123456789abcdef")])


if __name__ == "__main__":
    unittest.main()
