"""Narrow structured tool router.

Every action Marvi can take on the world passes through this registry. A tool
declares its exact argument names and types up front; anything else is refused
before a handler ever runs. Handlers are plain callables, so sidecars stay
behind adapters instead of leaking transport details into the router.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from typing import Any


class ToolRouterError(Exception):
    """A tool was named or called in a way the registry refuses."""


class UnknownToolError(ToolRouterError):
    pass


class InvalidArgumentsError(ToolRouterError):
    pass


@dataclass(frozen=True)
class ToolSpec:
    name: str
    description: str
    arguments: dict[str, type]
    sensitive: bool
    handler: Callable[..., Any]
    optional: dict[str, type] = field(default_factory=dict)
    # An external write reaches outside this machine and cannot be undone by
    # repeating it — a sent email is not a light switch. These are deduplicated.
    external: bool = False
    #: What each argument means, by name, for the model choosing values for it.
    #:
    #: Every schema went out as a bare `{"type": "string"}`, so the model had
    #: only the argument's name to go on — and both API guides say the same
    #: thing: describe the purpose of each parameter and its format. This is
    #: where that description lives. Optional, so a tool that has not been
    #: given one still registers; the name alone is what it always had.
    describes: dict[str, str] = field(default_factory=dict)

    def summary(self, arguments: dict[str, Any]) -> str:
        """One short human line for the Island and the audit trail."""
        if not arguments:
            return self.description
        rendered = ", ".join(f"{key}={value}" for key, value in sorted(arguments.items()))
        return f"{self.description} ({rendered})"


def _type_matches(value: Any, expected: type) -> bool:
    # ponytail: bool is an int subclass in Python; a checkbox is never a brightness.
    if expected is not bool and isinstance(value, bool):
        return False
    if expected is float:
        return isinstance(value, (int, float))
    return isinstance(value, expected)


def _coerce(value: Any, expected: type) -> Any:
    """A number written as a string is still that number.

    Models emit JSON, and a great many of them write `"lines": "40"` where the
    schema says integer -- the same model, on the same tool, sometimes both
    ways. Refusing that is technically correct and practically a broken tool:
    `marvi_logs` failed three times in a row with "argument lines must be int",
    Marvi spent her whole tool-call budget retrying it, and then answered from
    a log she never actually read.

    So a string is converted when it unambiguously is the declared type, and
    refused otherwise. Nothing else is coerced: an int where a string was asked
    for stays wrong, because that is a different mistake and quietly papering
    over it would hide a real schema disagreement.
    """
    if not isinstance(value, str) or expected is str:
        return value
    text = value.strip()
    if expected is bool:
        if text.lower() in ("true", "yes", "1"):
            return True
        if text.lower() in ("false", "no", "0"):
            return False
        return value
    if expected in (int, float):
        try:
            # `int("3.0")` raises, and a model that writes 3.0 for an integer
            # means three.
            number = float(text)
        except ValueError:
            return value
        if expected is int:
            return int(number) if number.is_integer() else value
        return number
    return value


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> None:
        self._tools[spec.name] = spec

    def __iter__(self) -> Iterator[ToolSpec]:
        return iter(self._tools.values())

    def __len__(self) -> int:
        return len(self._tools)

    def get(self, name: str) -> ToolSpec:
        try:
            return self._tools[name]
        except KeyError:
            raise UnknownToolError(f"unknown tool: {name}") from None

    def validate(self, spec: ToolSpec, arguments: dict[str, Any]) -> dict[str, Any]:
        """Return the accepted arguments, or refuse the call outright."""
        if not isinstance(arguments, dict):
            raise InvalidArgumentsError("arguments must be an object")

        allowed = {**spec.arguments, **spec.optional}
        unexpected = sorted(set(arguments) - set(allowed))
        if unexpected:
            raise InvalidArgumentsError(f"unexpected arguments: {', '.join(unexpected)}")

        missing = sorted(set(spec.arguments) - set(arguments))
        if missing:
            raise InvalidArgumentsError(f"missing arguments: {', '.join(missing)}")

        accepted = {}
        for key, value in arguments.items():
            value = _coerce(value, allowed[key])
            if not _type_matches(value, allowed[key]):
                raise InvalidArgumentsError(
                    f"argument {key} must be {allowed[key].__name__}"
                )
            accepted[key] = value
        return accepted

    def execute(self, spec: ToolSpec, arguments: dict[str, Any]) -> Any:
        return spec.handler(**arguments)
