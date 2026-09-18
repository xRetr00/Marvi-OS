"""Where a plugin gets to watch, and the one place it gets to say no.

Tool-call hooks lived on the `ToolRegistry` and could only observe. Two things
were missing and this is both of them:

* **Refusal.** A guardrail -- "nothing of Marvi's ever touches `D:\\Finance`" --
  is not expressible by watching. A granted `pre_tool_call` hook may return
  `{"action": "block", "message": ...}`, which becomes a refusal the model
  sees and the audit log records. A plugin
  written for that contract needs no changes.
* **More than tools.** A turn starting and ending, a memory being written, and
  a confirmation being raised are the other moments a plugin wants, and each
  one used to require a fork of Marvi to reach.

**Blocking is off unless the user turns it on.** A plugin cannot give itself
the power to refuse Marvi's tools by declaring it, any more than it can give
its own tools a pass on confirmation -- `register_tool` has always been a
request rather than a grant, and this is the same rule. Until a plugin is named
in `MARVI_HOOK_GUARDS`, a block it returns is logged once, with the fix, and
ignored. Installed plugins watch; granted plugins guard.

**A block narrows, never widens.** It cannot approve anything: confirmation
mode, the room's sleep rule and every other guard still run afterwards, exactly
as they did. The worst a granted hook can do is refuse too much, which is
visible immediately; the worst an *unhooked* veto could do is approve
something, which is not.

Failures are contained. A hook that raises is logged and the call goes on --
except a granted `pre_tool_call` that raises, which is treated as a refusal,
because a guardrail that crashed is not a guardrail that consented.
"""

from __future__ import annotations

import os
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

#: The ones a granted plugin can refuse. Only tool calls: blocking a turn would
#: leave the user talking to a Marvi that cannot answer and cannot say why.
CAN_BLOCK = ("pre_tool_call",)

#: Which plugins the user has allowed to refuse a tool call, comma separated.
#: `*` grants every installed plugin, for somebody who wants that and says so.
GUARDS_SETTING = "MARVI_HOOK_GUARDS"


def may_block(plugin: str) -> bool:
    """Whether this plugin has been granted the power to refuse a call."""
    granted = {
        name.strip().lower()
        for name in os.environ.get(GUARDS_SETTING, "").replace(";", ",").split(",")
        if name.strip()
    }
    return "*" in granted or plugin.strip().lower() in granted


class Hooks:
    """One set of handlers. Instances rather than a module global so a test --
    and the tool registry -- can have their own without leaking into the next."""

    def __init__(self) -> None:
        self._handlers: dict[str, list[Callable[..., Any]]] = {}
        #: Handlers whose refusals count, by identity. Empty by default: a hook
        #: watches until the user grants it more.
        self._guards: set[int] = set()
        #: Who registered each handler, so a log line names the plugin rather
        #: than a function nobody can place.
        self._named: dict[int, str] = {}
        #: Plugins already told their block was ignored. Once each, not once a call.
        self._warned: set[str] = set()

    def register(
        self, event: str, handler: Callable[..., Any], *, guard: bool = False, who: str = ""
    ) -> None:
        """Add a handler. `guard=True` means its refusals count -- see `may_block`."""
        if event not in EVENTS:
            raise ValueError(f"unknown hook {event!r}")
        if guard and event not in CAN_BLOCK:
            raise ValueError(f"{event!r} cannot refuse anything")
        self._handlers.setdefault(event, []).append(handler)
        if guard:
            self._guards.add(id(handler))
        self._named[id(handler)] = who or getattr(handler, "__qualname__", "a plugin")

    def clear(self) -> None:
        self._handlers.clear()
        self._guards.clear()
        self._named.clear()
        self._warned.clear()

    def registered(self, event: str) -> int:
        return len(self._handlers.get(event, ()))

    def guards(self, event: str = "pre_tool_call") -> int:
        """How many of this event's handlers may actually refuse a call."""
        return sum(1 for one in self._handlers.get(event, ()) if id(one) in self._guards)

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
        """Run the handlers. Returns a refusal reason, or "" to proceed.

        A handler that was not granted guard status still runs -- watching is
        what every hook is for -- and whatever it returns is ignored.
        """
        if event not in CAN_BLOCK:
            self.fire(event, **payload)
            return ""
        for handler in self._handlers.get(event, ()):
            guarding = id(handler) in self._guards
            who = self._named.get(id(handler), "a plugin")
            try:
                answer = handler(**payload)
            except Exception as exc:
                if not guarding:
                    log.warning(
                        "hook failed",
                        extra={"marvi_error": f"{event}: {type(exc).__name__}: {exc}"},
                    )
                    continue
                # A guardrail that crashed has not consented to anything.
                log.warning(
                    "guard hook failed; treating as a refusal",
                    extra={"marvi_error": f"{who}: {type(exc).__name__}: {exc}"},
                )
                return f"{who} failed while checking this ({type(exc).__name__})"
            if not (isinstance(answer, dict) and str(answer.get("action", "")).lower() == "block"):
                continue
            if not guarding:
                self._say_ignored(who)
                continue
            reason = str(answer.get("message") or "").strip() or f"{who} refused this"
            log.info(
                "hook blocked a call",
                extra={
                    "marvi_tool": str(payload.get("tool_name", "")),
                    "marvi_why": reason[:200],
                },
            )
            return reason
        return ""

    def _say_ignored(self, who: str) -> None:
        """Once per plugin, with the fix: a block nobody granted does nothing,
        and an author should not have to read this file to find that out."""
        if who in self._warned:
            return
        self._warned.add(who)
        log.warning(
            "a hook asked to block a tool call and is not allowed to",
            extra={
                "marvi_plugin": who,
                "marvi_fix": f"set {GUARDS_SETTING}={who} to allow it; it watches either way",
            },
        )


#: Everything that is not a tool call fires here. The tool registry owns its
#: own set, because a registry built for one test must not answer for another.
shared = Hooks()
