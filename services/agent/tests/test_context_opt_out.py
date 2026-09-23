"""LiveKit context replacement across opt-out / opt-in, with real SDK objects."""

import httpx
import pytest
from livekit.agents import llm

from marvi_agent.session import STAGED, MarviVoiceAgent
from marvi_agent.tools import GatewayTools


@pytest.mark.asyncio
async def test_active_session_replaces_context_and_removes_staged_recall():
    state = {"blocks": ["private-room-context"], "memory_allowed": True}
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda _: httpx.Response(200, json=state)
    )) as client:
        agent = MarviVoiceAgent()
        tools_before = list(agent.tools)
        agent.context_gateway = GatewayTools(client=client)
        agent.context_base = agent.instructions
        await agent.refresh_context()
        assert "private-room-context" in agent.instructions
        turn = llm.ChatContext.empty()
        turn.add_message(role="system", content=agent.instructions)
        turn.add_message(role="system", content=STAGED + " private-memory")
        turn.add_message(role="user", content="what is happening?")
        await agent.update_chat_ctx(turn)

        state.update(blocks=[], memory_allowed=False)
        await agent.refresh_context(turn)
        assert "private-room-context" not in agent.instructions
        assert not agent.context_memory_allowed
        assert all("private-room-context" not in (getattr(i, "text_content", "") or "") for i in turn.items)
        assert all("private-memory" not in (getattr(i, "text_content", "") or "") for i in turn.items)
        assert all("private-memory" not in (getattr(i, "text_content", "") or "") for i in agent.chat_ctx.items)
        assert agent.tools == tools_before  # Explicit tools stay available.

        state.update(blocks=["fresh-room-context"], memory_allowed=True)
        await agent.refresh_context(turn)
        assert agent.instructions.count("fresh-room-context") == 1
        assert agent.context_memory_allowed
        await agent.refresh_context(turn)
        assert agent.instructions.count("fresh-room-context") == 1


@pytest.mark.asyncio
async def test_context_fetch_failure_drops_stale_context():
    async with httpx.AsyncClient(transport=httpx.MockTransport(
        lambda _: httpx.Response(503)
    )) as client:
        agent = MarviVoiceAgent()
        agent.context_base = agent.instructions
        agent.context_gateway = GatewayTools(client=client)
        await agent.update_instructions(agent.instructions + " old-private-context")
        turn = llm.ChatContext.empty()
        turn.add_message(role="system", content=agent.instructions)
        await agent.refresh_context(turn)
        assert agent.instructions == agent.context_base
        assert not agent.context_memory_allowed
        assert turn.items[0].text_content == agent.context_base
