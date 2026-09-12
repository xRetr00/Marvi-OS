"""A tiny ACP agent for tests: the real protocol over stdio, scripted by the task.

The task text chooses what it does, so one fixture covers every path:

    ask:<kind>   request permission for a tool call of that kind, report the answer
    slow         wait until cancelled, then stop with `cancelled`
    refuse       end with `refusal`

It always sends a plan, a message and a tool call, and reports the session mode
it was put in, so a test can see the mode Marvi chose.
"""

from __future__ import annotations

import asyncio
import re
from contextlib import suppress
from typing import Any

from acp import (
    PROTOCOL_VERSION,
    plan_entry,
    run_agent,
    start_tool_call,
    update_agent_message_text,
    update_plan,
    update_tool_call,
)
from acp.schema import (
    InitializeResponse,
    NewSessionResponse,
    PermissionOption,
    PromptResponse,
    SessionMode,
    SessionModeState,
    ToolCallUpdate,
)


class Fake:
    def __init__(self) -> None:
        self.conn: Any = None
        self.mode = "default"
        self.cancelled = asyncio.Event()

    def on_connect(self, conn: Any) -> None:
        self.conn = conn

    async def initialize(self, protocol_version: int, **_: Any) -> InitializeResponse:
        return InitializeResponse(protocol_version=PROTOCOL_VERSION)

    async def new_session(self, cwd: str, **_: Any) -> NewSessionResponse:
        return NewSessionResponse(
            session_id="s1",
            modes=SessionModeState(
                current_mode_id="default",
                available_modes=[
                    SessionMode(id="default", name="Default"),
                    SessionMode(id="plan", name="Plan"),
                    SessionMode(id="acceptEdits", name="Accept edits"),
                ],
            ),
        )

    async def set_session_mode(self, session_id: str, mode_id: str, **_: Any) -> None:
        self.mode = mode_id

    async def cancel(self, session_id: str, **_: Any) -> None:
        self.cancelled.set()

    async def prompt(self, session_id: str, prompt: list[Any], **_: Any) -> PromptResponse:
        # Only the task decides, not Marvi's standing brief above it -- that
        # brief says "refuse" and "slow" in passing.
        task = " ".join(getattr(block, "text", "") for block in prompt).split("# The task")[-1]
        say = self.conn.session_update
        await say(session_id, update_plan([plan_entry("Look at it", status="in_progress")]))
        await say(session_id, update_agent_message_text(f"Starting in mode={self.mode}."))
        await say(session_id, start_tool_call("t1", "Read calc.py", kind="read", status="pending"))
        await say(session_id, update_tool_call("t1", status="completed"))

        if "slow" in task:
            with suppress(TimeoutError):
                await asyncio.wait_for(self.cancelled.wait(), timeout=20)
            return PromptResponse(stop_reason="cancelled")
        if "refuse" in task:
            await say(session_id, update_agent_message_text("I will not do that."))
            return PromptResponse(stop_reason="refusal")

        answer = "no permission asked"
        if match := re.search(r"ask:(\w+)", task):
            kind = match.group(1)
            await say(session_id, start_tool_call("t2", f"A {kind} step", kind=kind, status="pending"))
            response = await self.conn.request_permission(
                session_id,
                ToolCallUpdate(tool_call_id="t2", title=f"A {kind} step", kind=kind),
                [
                    PermissionOption(option_id="yes", name="Allow", kind="allow_once"),
                    PermissionOption(option_id="no", name="Reject", kind="reject_once"),
                ],
            )
            outcome = response.outcome
            allowed = getattr(outcome, "outcome", "") == "selected" and outcome.option_id == "yes"
            await say(session_id, update_tool_call("t2", status="completed" if allowed else "failed"))
            answer = "allowed" if allowed else "rejected"
        await say(
            session_id,
            update_plan([plan_entry("Look at it", status="completed")]),
        )
        await say(session_id, update_agent_message_text(f"Done: {answer}, mode={self.mode}."))
        return PromptResponse(stop_reason="end_turn")


if __name__ == "__main__":
    asyncio.run(run_agent(Fake()))
