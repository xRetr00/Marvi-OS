"""Where a plugin gets to watch, and the one place it gets to say no.

Tool-call hooks lived on the `ToolRegistry` and could only observe. Two things
were missing and this is both of them:

* **Refusal.** A guardrail -- "nothing of Marvi's ever touches `D:\\Finance`" --
  is not expressible by watching. A `pre_tool_call` hook may now return
  `{"action": "block", "message": ...}`, which becomes a refusal the model
  sees and the audit log records. It is Hermes Agent's shape, so a plugin
  written for that contract needs no changes.
* **More than tools.** A turn starting and ending, a memory being written, and
  a confirmation being raised are the other moments a plugin wants, and each
  one used to require a fork of Marvi to reach.

**A block narrows, never widens.** It cannot approve anything: confirmation
mode, the room's sleep rule and every other guard still run afterwards, exactly
as they did. The worst a broken hook can do is refuse too much, which is
visible immediately; the worst an *unhooked* veto could do is approve
something, which is not.

Failures are contained. A hook that raises is logged and the call goes on --
except a `pre_tool_call` that raises, which is treated as a block, because a
guardrail that crashed is not a guardrail that consented.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .logs import get_logger

log = get_logger("plugins")

#: Every event Marvi raises. A plugin may register for any of them.
EVENTS = (
    "pre_tool_call",
    "post_tool_call",
    "pre_turn",
    "post_turn",
    "on_memory_write",
    "on_confirmation",
)

#: The ones a plugin can refuse. Only tool calls: blocking a turn would leave
#: the user talking to a Marvi that cannot answer and cannot say why.
CAN_BLOCK = ("pre_tool_call",)


class Hooks:
    """One set of handlers. Instances rather than a module global so a test --
    and the tool registry -- can have their own without leaking into the next."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable[..., Any]]] = {}

    def register(self, event: str, handler: Callable[..., Any]) -> None:
        if event not in EVENTS:
            raise ValueError(f"unknown hook {event!r}")
        self._handlers.setdefault(event, []).append(handler)

    def clear(self) -> None:
        self._handlers.clear()

    def registered(self, event: str) -> int:
        return len(self._handlers.get(event, ()))

    def fire(self, event: str, **payload: Any) -> None:
        """Tell every handler. Nothing they return is read."""
        for handler in self._handlers.get(event, ()):
            try:
                handler(**payload)
            except Exception as exc:
                log.warning(
                    "hook failed",
                    extra={"marvi_error": f"{event}: {type(exc).__name__}: {exc}"},
                )

    def veto(self, event: str, **payload: Any) -> str:
        """Run handlers that may refuse. Returns the reason, or "" to proceed."""
        if event not in CAN_BLOCK:
            self.fire(event, **payload)
            return ""
        for handler in self._handlers.get(event, ()):
            try:
                answer = handler(**payload)
            except Exception as exc:
                # A guardrail that crashed has not consented to anything.
                log.warning(
                    "hook failed; treating as a refusal",
                    extra={"marvi_error": f"{event}: {type(exc).__name__}: {exc}"},
                )
                return f"a plugin hook failed: {type(exc).__name__}"
            if isinstance(answer, dict) and str(answer.get("action", "")).lower() == "block":
                reason = str(answer.get("message") or "").strip() or "a plugin refused this"
                log.info(
                    "hook blocked a call",
                    extra={"marvi_tool": str(payload.get("tool_name", "")), "marvi_why": reason[:200]},
                )
                return reason
        return ""


#: Everything that is not a tool call fires here. The tool registry owns its
#: own set, because a registry built for one test must not answer for another.
shared = Hooks()
