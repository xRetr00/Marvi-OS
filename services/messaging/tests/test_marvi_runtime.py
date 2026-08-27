from __future__ import annotations

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

    def test_marvi_environment_activates_only_the_bundled_engine(self):
        from marvi_messaging._engine import activate

        engine = SERVICE_ROOT / "marvi_messaging" / "engine"
        with tempfile.TemporaryDirectory() as profile, patch.dict(
            os.environ,
            {
                "MARVI_MESSAGING_HOME": profile,
                "MARVI_MESSAGING_ENGINE_ROOT": str(engine),
                "MARVI_MESSAGING_EXTERNAL_SUPERVISOR": "1",
            },
            clear=False,
        ):
            self.assertEqual(activate(managed=True), engine.resolve())
            self.assertEqual(os.environ["MARVI_MESSAGING_HOME"], profile)
            self.assertEqual(os.environ["MARVI_MESSAGING_MANAGED"], "marvi-os")
            self.assertEqual(os.environ["AI_AGENT"], "marvi-os-messaging")
            self.assertEqual(os.environ["MARVI_MESSAGING_DISABLE_LAZY_INSTALLS"], "1")

    def test_owned_runtime_contains_no_predecessor_runtime_namespace(self):
        runtime = SERVICE_ROOT / "marvi_messaging"
        predecessor = "her" + "mes"
        for path in runtime.rglob("*"):
            if not path.is_file() or path.suffix.lower() not in {
                ".py", ".toml", ".json", ".md", ".yaml", ".yml"
            }:
                continue
            source = path.read_text(encoding="utf-8", errors="ignore").lower()
            with self.subTest(path=path.relative_to(runtime)):
                self.assertNotIn(predecessor, source)
                self.assertNotIn("marvi-agent", source)
                self.assertNotIn("marvi agent", source)

    def test_gateway_setup_configures_adapters_without_service_install(self):
        from marvi_messaging.configuration import run_setup

        calls: list[str] = []
        support_package = types.ModuleType("runtime_support")
        config_module = types.ModuleType("runtime_support.config")
        config_module.DEFAULT_CONFIG = {}
        config_module.ensure_marvi_home = lambda: calls.append("home")
        config_module.load_config = lambda: {}
        config_module.save_config = lambda config: calls.append("save")
        setup_module = types.ModuleType("runtime_support.setup")
        setup_module.SETUP_SECTIONS = [
            ("gateway", "Messaging Platforms", lambda config: calls.append("upstream-service-setup"))
        ]
        setup_module.prompt_checklist = lambda prompt, choices, selected: [0]
        gateway_module = types.ModuleType("runtime_support.gateway")
        gateway_module._all_platforms = lambda: [{"emoji": "#", "label": "Test"}]
        gateway_module._platform_status = lambda platform: "not configured"
        gateway_module._configure_platform = lambda platform: calls.append("adapter")

        with (
            patch("marvi_messaging.configuration.activate"),
            patch.dict(
                sys.modules,
                {
                    "runtime_support": support_package,
                    "runtime_support.config": config_module,
                    "runtime_support.setup": setup_module,
                    "runtime_support.gateway": gateway_module,
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

    def test_gateway_liveness_recognizes_the_marvi_module_entrypoint(self):
        from marvi_messaging._engine import activate

        with tempfile.TemporaryDirectory() as profile, patch.dict(
            os.environ, {"MARVI_MESSAGING_HOME": profile}, clear=False
        ):
            activate(managed=True)
            from gateway.status import looks_like_gateway_command_line

            self.assertTrue(
                looks_like_gateway_command_line(
                    'python.exe -m marvi_messaging.main gateway run --external-supervisor'
                )
            )
            self.assertTrue(
                looks_like_gateway_command_line(
                    'python.exe C:/Marvi/runtime/marvi_messaging/main.py gateway run'
                )
            )


if __name__ == "__main__":
    unittest.main()
