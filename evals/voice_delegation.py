"""A spoken session that hands desktop work to Jarvi, through the real pipeline.

The acceptance Phase 16 exists for: asked to do something on the desktop, Marvi
answers within the turn, can be talked to while Jarvi works, and says what
happened when the report arrives -- without the owner asking.

Everything is production except the microphone and the speaker, the same seam
`live_conversation.py` uses: the real `MarviVoiceAgent`, persona, context
blocks, tool catalogue (without the multi-step computer tools), the
`on_end_of_turn` path, and `delegated.py`'s watcher. The Gateway is this
checkout's, served on its own port with its lifespan off, so a running Marvi's
Telegram poller and scheduler are not duplicated. Jarvi drives the real Cua
worker.

    .venv/Scripts/python.exe evals/voice_delegation.py [--json out.json]
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import pathlib
import sys
import threading
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
_ROOT = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_ROOT / "services/agent/src"))
sys.path.insert(0, str(_ROOT / "services/gateway/src"))
sys.path.insert(0, str(_ROOT / "evals"))

PORT = 8799
ASK = "Can you open Notepad, tell me the title of its window, and then close it?"
MEANWHILE = "While that's going, what's seven times eight?"
AFTER = "Okay, thanks."


def serve_gateway() -> object:
    import uvicorn

    from marvi_gateway.app import create_app

    app = create_app(version="voice-delegation-eval")
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, lifespan="off", log_level="warning"))
    threading.Thread(target=server.run, daemon=True, name="eval-gateway").start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    else:
        raise RuntimeError("the Gateway did not start")
    # Warmed before the first turn. The first run of this eval was cold: the
    # embedding model's import took 21 s and `/context` 12 s inside this same
    # process, and the first turn's tool call timed out as "Gateway
    # unreachable". A real Gateway is its own process and is warm long before
    # anyone says a word, so a cold one here measures the harness, not Marvi.
    import httpx

    base = f"http://127.0.0.1:{PORT}"
    started = time.monotonic()
    httpx.get(f"{base}/context", timeout=180)
    httpx.get(f"{base}/memory/recall", params={"text": "warm up"}, timeout=180)
    print(f"  (Gateway warmed in {time.monotonic() - started:.1f}s)\n", flush=True)
    return app


async def turn(session, agent, text: str) -> dict:
    from live_conversation import _end_of_turn

    started = time.monotonic()
    before = len(agent.chat_ctx.items)
    session._activity.on_end_of_turn(_end_of_turn(text))
    for _ in range(1200):
        await asyncio.sleep(0.05)
        fresh = agent.chat_ctx.items[before:]
        # The last item is what matters: "One sec." followed by a tool call is
        # a turn still in progress, and stopping at the first spoken line
        # records the filler and misses the call.
        last = fresh[-1] if fresh else None
        spoke = (
            last is not None
            and getattr(last, "role", "") == "assistant"
            and str(getattr(last, "text_content", "") or "").strip()
        )
        if spoke and not session._activity._current_speech:
            break
    fresh = agent.chat_ctx.items[before:]
    row = {
        "heard": text,
        "said": " ".join(
            str(getattr(item, "text_content", "") or "")
            for item in fresh
            if getattr(item, "role", "") == "assistant"
        ).strip(),
        "tools": [getattr(item, "name", "") for item in fresh if getattr(item, "type", "") == "function_call"],
        "arguments": [
            getattr(item, "arguments", "") for item in fresh if getattr(item, "type", "") == "function_call"
        ],
        "seconds": round(time.monotonic() - started, 2),
    }
    print(f"  YOU    {text}\n  MARVI  {row['said'][:300] or '(nothing)'}")
    if row["tools"]:
        print(f"         tools: {', '.join(row['tools'])}")
    print(f"         {row['seconds']:.1f}s\n", flush=True)
    return row


async def converse(app) -> dict:
    from livekit.agents import AgentSession
    from livekit.agents.testing import fake_job_context

    from marvi_agent import delegated
    from marvi_agent.session import MarviVoiceAgent, _timed_llm, prefetch
    from marvi_agent.tools import GatewayTools

    gateway = GatewayTools()
    agent = MarviVoiceAgent(tools=gateway)
    session = AgentSession(llm=_timed_llm())
    runner = app.state.subagents
    evidence: dict = {"turns": []}
    with fake_job_context():
        await session.start(agent)
        prefetch.attach(agent, asyncio.get_running_loop())
        catalogue = await gateway.from_gateway()
        if catalogue:
            gateway.attach(agent)
            await agent.update_tools([*agent.tools, *catalogue])
        if blocks := await gateway.context_blocks():
            await agent.update_instructions(agent.instructions + "\n\n" + "\n\n".join(blocks))
        loaded = {getattr(tool, "info", None) and tool.info.name for tool in agent.tools}
        evidence["voice_has_computer_action"] = "computer_action" in loaded
        evidence["voice_has_delegate"] = "delegate" in loaded

        evidence["turns"].append(await turn(session, agent, ASK))
        jobs = runner.status()["jobs"]
        evidence["jarvi_running_after_first_turn"] = any(
            job["agent"] == "jarvi" and job["state"] in ("running", "awaiting_approval") for job in jobs
        )
        evidence["turns"].append(await turn(session, agent, MEANWHILE))
        evidence["jarvi_still_running_during_second_turn"] = any(
            job["agent"] == "jarvi" and job["state"] in ("running", "awaiting_approval")
            for job in runner.status()["jobs"]
        )

        # Wait for Jarvi, then for the voice watcher to pick the report up
        # (it polls every 15 s), exactly as a real session would.
        deadline = time.monotonic() + 300
        while time.monotonic() < deadline:
            job = next((one for one in runner.status()["jobs"] if one["agent"] == "jarvi"), None)
            if job and job["state"] == "awaiting_approval":
                print(f"  (approving for the eval: {job['action']})", flush=True)
                runner.approve(job["id"], True)
            if job and job["state"] not in ("running", "awaiting_approval"):
                break
            await asyncio.sleep(1)
        evidence["jarvi"] = {k: job[k] for k in ("state", "exit_reason", "seconds", "summary")} if job else None
        for _ in range(40):
            with delegated.jobs._lock:
                if delegated.jobs._ready:
                    break
            await asyncio.sleep(1)
        evidence["turns"].append(await turn(session, agent, AFTER))
        await session.aclose()
    return evidence


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", help="write the evidence here")
    args = parser.parse_args()

    from marvi_gateway.providers import config as provider_config

    for name, value in provider_config.read().items():
        os.environ.setdefault(name, value)
    os.environ["MARVI_GATEWAY_URL"] = f"http://127.0.0.1:{PORT}"

    app = serve_gateway()
    evidence = asyncio.run(converse(app))
    first, second, third = evidence["turns"]
    evidence["checks"] = {
        "voice_lacks_computer_action": not evidence["voice_has_computer_action"],
        # Across the first two turns: a filler ("One sec.") can end the first
        # turn's window before the call it preceded is recorded.
        "delegated_to_jarvi": any(
            name == "delegate" and "jarvi" in str(arguments).lower()
            for row in (first, second)
            for name, arguments in zip(row["tools"], row["arguments"])
        ),
        "answered_while_jarvi_worked": evidence["jarvi_still_running_during_second_turn"]
        and "56" in second["said"],
        "jarvi_completed": bool(evidence["jarvi"]) and evidence["jarvi"]["state"] == "completed",
        "report_said_unprompted": any(
            word in third["said"].lower() for word in ("notepad", "closed", "title", "untitled")
        ),
    }
    print(json.dumps(evidence["checks"], indent=1))
    if args.json:
        pathlib.Path(args.json).write_text(json.dumps(evidence, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
