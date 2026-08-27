"""Marvi-owned configuration API using pinned interactive section libraries."""

from __future__ import annotations

from pathlib import Path

from ._engine import activate


SECTIONS = ("model", "tts", "terminal", "gateway", "tools", "telemetry", "agent")


def config_path() -> Path:
    activate(managed=False)
    from runtime_support.config import get_config_path
    return get_config_path()


def is_configured() -> bool:
    return config_path().is_file()


def _configure_messaging_platforms() -> None:
    """Configure adapters without installing or restarting an upstream service."""
    from runtime_support.gateway import _all_platforms, _configure_platform, _platform_status
    from runtime_support.setup import prompt_checklist

    platforms = _all_platforms()
    choices: list[str] = []
    selected: list[int] = []
    for index, platform in enumerate(platforms):
        status = _platform_status(platform)
        choices.append(f"{platform['emoji']} {platform['label']}  ({status})")
        if status == "configured":
            selected.append(index)

    picked = prompt_checklist("Select messaging platforms to configure:", choices, selected)
    for index in picked:
        _configure_platform(platforms[index])
    if not picked:
        print("No messaging platforms selected. You can run Marvi setup again later.")


def run_setup(section: str = "gateway", *, reset: bool = False) -> None:
    """Configure one capability through Marvi's setup boundary.

    The interactive section implementations remain pinned upstream libraries;
    their CLI parser, command dispatcher, service installer, and application
    entrypoint are intentionally not used.
    """
    activate(managed=False)
    from runtime_support.config import DEFAULT_CONFIG, ensure_marvi_home, load_config, save_config
    from runtime_support.setup import SETUP_SECTIONS
    import copy

    if section not in SECTIONS:
        raise ValueError(f"Unknown messaging setup section: {section}")
    ensure_marvi_home()
    config = copy.deepcopy(DEFAULT_CONFIG) if reset else load_config()
    handlers = {key: (label, handler) for key, label, handler in SETUP_SECTIONS}
    handlers["gateway"] = ("Messaging Platforms", lambda _config: _configure_messaging_platforms())
    label, handler = handlers[section]
    print("\nMarvi OS Messaging Setup")
    print(f"Configuring: {label}\n")
    handler(config)
    save_config(config)
    print(f"\nMarvi {label.lower()} configuration complete.")
