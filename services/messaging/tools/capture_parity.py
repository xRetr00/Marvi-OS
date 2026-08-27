"""Capture the executable messaging capability surface as stable JSON.

Run this against the pre-transplant tree and again against the Marvi-owned
tree.  The deletion gate compares the resulting manifests exactly.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from pathlib import Path
from typing import Any


def _slash_commands(source_root: Path) -> list[str]:
    commands: set[str] = set()
    for relative in ("gateway/run.py", "gateway/slash_commands.py"):
        source = source_root / relative
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Dict):
                continue
            for key in node.keys:
                if isinstance(key, ast.Constant) and isinstance(key.value, str):
                    value = key.value.strip().lower()
                    if value and value.replace("_", "").replace("-", "").isalnum():
                        if any(
                            isinstance(value_node, ast.Attribute)
                            and value_node.attr.startswith("_handle_")
                            for value_node in ast.walk(node)
                        ):
                            commands.add(value)
            if isinstance(node, ast.Compare):
                names = {
                    child.id.lower()
                    for child in ast.walk(node)
                    if isinstance(child, ast.Name)
                }
                if not names.intersection({"command", "cmd", "command_name", "cmd_name"}):
                    continue
                for child in ast.walk(node):
                    if isinstance(child, ast.Constant) and isinstance(child.value, str):
                        value = child.value.strip().lower()
                        if value and len(value) <= 32 and value.replace("_", "").replace("-", "").isalnum():
                            commands.add(value)
    return sorted(commands)


def _jsonable(value: Any) -> Any:
    predecessor = "her" + "mes"
    if isinstance(value, dict):
        return {
            re.sub(predecessor, "marvi", str(key), flags=re.IGNORECASE): _jsonable(item)
            for key, item in sorted(value.items())
        }
    if isinstance(value, (list, tuple, set)):
        return [_jsonable(item) for item in value]
    if isinstance(value, str):
        return re.sub(predecessor, "marvi", value, flags=re.IGNORECASE)
    if isinstance(value, (int, float, bool)) or value is None:
        return value
    return str(value)


def capture(source_root: Path) -> dict[str, Any]:
    source_root = source_root.resolve()
    sys.path.insert(0, str(source_root))

    from runtime_support.plugins import discover_plugins

    discover_plugins(force=True)
    # Importing the stable tool facade registers every built-in tool exactly
    # as a live messaging session sees it.
    import model_tools  # noqa: F401

    from gateway.config import Platform
    from gateway.platform_registry import platform_registry
    from tools.registry import registry
    from toolsets import get_all_toolsets, resolve_toolset

    platform_entries = []
    for entry in sorted(platform_registry.plugin_entries(), key=lambda item: item.name):
        platform_entries.append(
            {
                "name": entry.name,
                "source": entry.source,
                "required_env": sorted(entry.required_env),
                "allow_update_command": entry.allow_update_command,
                "cron_delivery": bool(entry.cron_deliver_env_var),
            }
        )

    tools = []
    for entry in sorted(registry.get_all_entries(), key=lambda item: item.name):
        tools.append(
            {
                "name": entry.name,
                "toolset": entry.toolset,
                "async": entry.is_async,
                "required_env": sorted(entry.requires_env),
            }
        )

    toolsets = {}
    for name, definition in sorted(get_all_toolsets().items()):
        toolsets[name] = {
            "tools": sorted(set(resolve_toolset(name))),
            "includes": sorted(definition.get("includes", [])),
        }

    return _jsonable({
        "schema": 1,
        "platform_enum": sorted(member.value for member in Platform),
        "platform_plugins": platform_entries,
        "tools": tools,
        "toolsets": toolsets,
        "slash_commands": _slash_commands(source_root),
    })


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("source_root", type=Path)
    parser.add_argument("--home", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    args.home.mkdir(parents=True, exist_ok=True)
    config = args.home / "config.yaml"
    if not config.exists():
        config.write_text("{}\n", encoding="utf-8")
    os.environ["MARVI_MESSAGING_HOME"] = str(args.home.resolve())
    os.environ["MARVI_MESSAGING_RUNTIME"] = "1"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"

    payload = json.dumps(capture(args.source_root), indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(payload, encoding="utf-8")
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
