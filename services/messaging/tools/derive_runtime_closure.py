"""Derive the internal Python source closure for Marvi messaging.

This is a migration and update-review tool, not a runtime loader.  It follows
static imports from the Marvi entry seeds and all platform plugins, then emits
the exact internal files those modules reference.  Dynamic registries and
non-Python assets are audited separately by the parity tests.
"""

from __future__ import annotations

import argparse
import ast
import json
from collections import deque
from pathlib import Path


ENTRY_SEEDS = (
    "gateway/run.py",
    "gateway/status.py",
    "gateway/pairing.py",
    "runtime_support/config.py",
    "runtime_support/setup.py",
    "runtime_support/gateway.py",
)


def _module_candidates(root: Path, module: str) -> tuple[Path, ...]:
    parts = tuple(part for part in module.split(".") if part)
    if not parts:
        return ()
    base = root.joinpath(*parts)
    return (base.with_suffix(".py"), base / "__init__.py")


def _package_name(root: Path, source: Path) -> str:
    relative = source.relative_to(root).with_suffix("")
    parts = list(relative.parts)
    if parts[-1] == "__init__":
        parts.pop()
    else:
        parts.pop()
    return ".".join(parts)


def _resolve_imports(root: Path, source: Path) -> set[Path]:
    try:
        tree = ast.parse(source.read_text(encoding="utf-8"), filename=str(source))
    except (OSError, SyntaxError, UnicodeDecodeError):
        return set()

    package = _package_name(root, source)
    resolved: set[Path] = set()
    for node in ast.walk(tree):
        modules: list[str] = []
        if isinstance(node, ast.Import):
            modules.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            base = node.module or ""
            if node.level:
                package_parts = package.split(".") if package else []
                keep = max(0, len(package_parts) - node.level + 1)
                base = ".".join([*package_parts[:keep], *([base] if base else [])])
            if base:
                modules.append(base)
                modules.extend(f"{base}.{alias.name}" for alias in node.names if alias.name != "*")
        elif (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "import_module"
            and node.args
            and isinstance(node.args[0], ast.Constant)
            and isinstance(node.args[0].value, str)
        ):
            modules.append(node.args[0].value)

        for module in modules:
            for candidate in _module_candidates(root, module):
                if candidate.is_file():
                    resolved.add(candidate)
                    break
    return resolved


def derive(root: Path) -> list[str]:
    seeds = [root / seed for seed in ENTRY_SEEDS]
    seeds.extend((root / "plugins" / "platforms").rglob("*.py"))
    queue = deque(path.resolve() for path in seeds if path.is_file())
    found: set[Path] = set()
    while queue:
        source = queue.popleft()
        if source in found:
            continue
        found.add(source)
        queue.extend(_resolve_imports(root, source) - found)
    return sorted(path.relative_to(root).as_posix() for path in found)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("root", type=Path)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    files = derive(args.root.resolve())
    if args.json:
        print(json.dumps({"count": len(files), "files": files}, indent=2))
    else:
        print("\n".join(files))
        print(f"\n# {len(files)} Python files", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
