"""Voice tool tests.

These drive the real Marvi Gateway ASGI app over an httpx transport, so the
agent's tools exercise the same router, tokens, and audit trail the Island
uses. Only the smart-room sidecar itself is substituted.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx
import pytest
from livekit.agents import ToolError
from livekit.agents.llm.utils import build_legacy_openai_schema

GATEWAY_SRC = Path(__file__).resolve().parents[2] / "gateway" / "src"
if str(GATEWAY_SRC) not in sys.path:
    sys.path.insert(0, str(GATEWAY_SRC))

from marvi_gateway.app import create_app  # noqa: E402
from marvi_gateway.runtime import RuntimeStore  # noqa: E402
from marvi_gateway.tools import ToolRegistry, ToolSpec  # noqa: E402

from marvi_agent.tools import GatewayTools  # noqa: E402


@pytest.mark.asyncio
async def test_location_tools_follow_gateway_configuration_and_voice_budget(tmp_path, monkeypatch):
    import time

    from marvi_gateway.location import Place, Settings, register_location_tools

    monkeypatch.setenv("MARVI_LOCAL_TOKEN", "voice-location-token")
    registry = ToolRegistry()
    app = create_app(version="0.1.0-test", tools=registry,
                     runtime=RuntimeStore(audit_path=tmp_path / "audit.jsonl"))
    service = app.state.location
    register_location_tools(registry, service)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://marvi.local") as client:
        voice = GatewayTools(base_url="http://marvi.local", client=client)
        await voice.from_gateway()
        off = await voice.tool_call(None, name="get_weather")
        assert "Choose a location" in off
        service.configure(Settings(mode="saved", saved=Place(latitude=40, longitude=31,
            label="Test home", timezone="Europe/Istanbul")))
        service.cache_key = (40, 31)
        service.cached = {"fetched_at": time.time(), "timezone": "Europe/Istanbul",
            "current": {"time": "2026-09-12T10:00", "temperature_2m": 22, "apparent_temperature": 23,
                "relative_humidity_2m": 60, "wind_speed_10m": 5, "weather_code": 3},
            "daily": {"time": ["2026-09-12", "2026-09-13", "2026-09-14"],
                "temperature_2m_min": [18, 19, 20], "temperature_2m_max": [25, 26, 27],
                "precipitation_probability_max": [10, 20, 30], "weather_code": [3, 3, 3],
                "sunrise": ["2026-09-12T06:30"], "sunset": ["2026-09-12T19:15"]}}
        weather = await voice.tool_call(None, name="get_weather")
        assert "22 C" in weather and "2026-09-14" in weather and "Sunrise" in weather
        assert "cut short" not in weather
        assert voice.pending_token is None
        clock = await voice.tool_call(None, name="get_local_time")
        assert "Europe/Istanbul" in clock
        service.configure(Settings(mode="off"))
        disabled = await voice.tool_call(None, name="get_location")
        assert "Test home" not in disabled


@pytest.fixture
def gateway(tmp_path):
    executed: list[tuple[str, dict]] = []
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="room_state",
            description="Read the current room state",
            arguments={},
            sensitive=False,
            handler=lambda: {
                "live": True,
                "state": {
                    "light": {"on": True, "brightness": 40},
                    "modes": {"active_mode": "focus"},
                    "presence": {"detected": True},
                },
            },
        )
    )
    registry.register(
        ToolSpec(
            name="room_set_light",
            description="Change the room light",
            arguments={"on": bool},
            optional={"brightness": int},
            sensitive=True,
            handler=lambda **args: executed.append(("room_set_light", args)) or {"ok": True},
        )
    )
    registry.register(
        ToolSpec(
            name="room_set_mode",
            description="Change the room mode",
            arguments={"mode": str},
            sensitive=True,
            handler=lambda **args: executed.append(("room_set_mode", args)) or {"ok": True},
        )
    )
    runtime = RuntimeStore(audit_path=tmp_path / "audit.jsonl")
    app = create_app(version="0.1.0-test", runtime=runtime, tools=registry)
    client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://marvi.local"
    )
    return client, runtime, executed


@pytest.fixture
def voice(gateway):
    client, _, _ = gateway
    return GatewayTools(base_url="http://marvi.local", client=client)


def test_tool_schemas_are_voice_sized_and_hide_transport(voice) -> None:
    schemas = {
        schema["function"]["name"]: schema["function"]
        for schema in (build_legacy_openai_schema(tool) for tool in voice.as_list())
    }

    assert set(schemas) == {
        "room_state",
        "room_light",
        "room_mode",
        "recall",
        "remember",
        # Written for speech because "forget X" is how the sentence is said.
        # The catalogue's `memory_forget` was the only form for a while, and
        # among fifty-five tools the model could not find it: asked to forget
        # Zed it called `process_list`, then `memory_unlink`, reporting success
        # both times.
        "forget",
        # The bridge, from Hermes Agent. See `tool_call`.
        "tool_call",
        "approve_pending_action",
        "deny_pending_action",
        # Hand-written for a different reason than the rest: it is an async
        # tool, and the generic bridge cannot build one from a JSON schema.
        "await_delegated",
    }
    # RunContext and the gateway token never appear in the LLM-visible schema.
    assert schemas["room_light"]["parameters"]["required"] == ["on"]
    assert set(schemas["room_light"]["parameters"]["properties"]) == {
        "on",
        "brightness",
        "color_temp",
    }
    assert schemas["approve_pending_action"]["parameters"]["properties"] == {}


@pytest.mark.asyncio
async def test_reading_room_state_needs_no_confirmation(voice, gateway) -> None:
    client, _, _ = gateway
    async with client:
        spoken = await voice.room_state(None)

    assert "light on at 40 percent" in spoken
    assert "mode focus" in spoken
    assert voice.pending_token is None


@pytest.mark.asyncio
async def test_write_asks_first_then_spoken_approval_executes_it(voice, gateway) -> None:
    client, _, executed = gateway
    async with client:
        asked = await voice.room_light(None, on=True, brightness=30)
        token = voice.pending_token
        approved = await voice.approve_pending_action(None)

    assert "needs confirmation" in asked
    assert token
    assert executed == [("room_set_light", {"on": True, "brightness": 30})]
    assert approved == "Done."
    assert voice.pending_token is None


@pytest.mark.asyncio
async def test_spoken_denial_never_executes(voice, gateway) -> None:
    client, _, executed = gateway
    async with client:
        await voice.room_mode(None, mode="sleep")
        denied = await voice.deny_pending_action(None)

    assert denied == "Cancelled."
    assert executed == []


@pytest.mark.asyncio
async def test_spoken_approval_and_island_share_one_token(voice, gateway) -> None:
    """The Island resolving first must leave nothing for the voice path to approve."""
    client, _, executed = gateway
    async with client:
        await voice.room_light(None, on=False)
        token = voice.pending_token
        island = await client.post(
            f"/confirmations/{token}",
            json={"decision": "approve", "arguments": {"on": False}},
        )
        with pytest.raises(ToolError, match="already"):
            await voice.approve_pending_action(None)

    assert island.json()["status"] == "executed"
    assert executed == [("room_set_light", {"on": False})]


@pytest.mark.asyncio
async def test_approving_with_nothing_pending_is_refused(voice, gateway) -> None:
    client, _, executed = gateway
    async with client:
        with pytest.raises(ToolError, match="no action waiting"):
            await voice.approve_pending_action(None)

    assert executed == []


@pytest.mark.asyncio
async def test_yolo_skips_confirmation_for_the_voice_path_too(voice, gateway) -> None:
    client, runtime, executed = gateway
    runtime.set_yolo(True)
    async with client:
        spoken = await voice.room_mode(None, mode="relax")

    # A receipt, not a bare "Done." -- what came back used to say nothing about
    # which tool ran or with what, so the model had no record to check its own
    # claims against. See `tools.receipt`.
    assert spoken == "[did room_set_mode mode=relax -> ok] Done."
    assert voice.pending_token is None
    assert executed == [("room_set_mode", {"mode": "relax"})]

    records = [json.loads(line) for line in runtime.audit_path.read_text().splitlines()]
    assert [record["event"] for record in records] == ["requested", "executed"]
    assert records[-1]["mode"] == "yolo"


@pytest.mark.asyncio
async def test_invalid_arguments_are_reported_to_the_llm_not_raised_as_a_crash(
    voice, gateway
) -> None:
    client, _, executed = gateway
    async with client:
        with pytest.raises(ToolError):
            await voice.room_mode(None, mode=42)

    assert executed == []


@pytest.mark.asyncio
async def test_unreachable_gateway_is_a_tool_error_not_a_session_failure() -> None:
    offline = GatewayTools(base_url="http://127.0.0.1:1")
    with pytest.raises(ToolError, match="unreachable"):
        await offline.room_state(None)


# -- prompt context ------------------------------------------------------------


async def test_the_prompt_context_comes_from_the_gateway() -> None:
    """Voice builds its own instructions, so anything the Gateway assembles --
    the skill catalogue, where this installation lives -- has to be fetched or
    it reaches chat only. That is exactly how voice ended up with seven tools
    while chat had seventeen."""
    import httpx

    from marvi_agent.tools import GatewayTools

    def handle(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/context"
        return httpx.Response(200, json={"blocks": ["# Skills you can use\n\n- a: b", "  ", ""]})

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    blocks = await GatewayTools(client=client).context_blocks()
    await client.aclose()

    # Blank blocks dropped: an empty heading spends tokens saying nothing.
    assert blocks == ["# Skills you can use\n\n- a: b"]


async def test_a_gateway_that_cannot_answer_costs_the_catalogue_not_the_voice() -> None:
    import httpx

    from marvi_agent.tools import GatewayTools

    def refuse(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    client = httpx.AsyncClient(transport=httpx.MockTransport(refuse))
    blocks = await GatewayTools(client=client).context_blocks()
    await client.aclose()

    assert blocks == []


# -- work that takes minutes ---------------------------------------------------


class _Nothing:
    """An async context manager that does nothing, standing in for the filler."""

    async def __aenter__(self):
        return None

    async def __aexit__(self, *_exc):
        return False


class FakeUpdates:
    """Stands in for RunContext: records what was said and when control went
    back to the model."""

    def __init__(self) -> None:
        self.updates: list[str] = []
        self.fillers: list[tuple[str, float, float | None]] = []

    async def update(self, message, *, template=None) -> None:
        self.updates.append(str(message))

    def with_filler(self, source, *, delay=0, interval=None, max_steps=None):
        self.fillers.append((str(source), delay, interval))

        return _Nothing()


async def test_waiting_hands_control_back_before_the_job_finishes() -> None:
    """The whole mechanism. The first update is the tool's synthetic return, so
    Marvi speaks it and carries on while the body below keeps polling. Without
    it a five-minute job is five minutes of dead air."""
    import httpx

    from marvi_agent.tools import GatewayTools

    states = iter(["running", "running", "done"])

    def handle(request: httpx.Request) -> httpx.Response:
        state = next(states)
        return httpx.Response(
            200,
            json={
                "status": "ok",
                "result": {"ok": True, "state": state, "output": "found it", "id": "3f2a"},
            },
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    tools = GatewayTools(client=client)
    context = FakeUpdates()

    import marvi_agent.tools as tools_module

    original, tools_module.POLL_EVERY = tools_module.POLL_EVERY, 0.0
    try:
        answer = await tools.await_delegated.__wrapped__(tools, context, "3f2a")
    finally:
        tools_module.POLL_EVERY = original
        await client.aclose()

    assert context.updates, "control was never handed back; the conversation would block"
    assert "3f2a" in context.updates[0]
    assert "found it" in answer


async def test_the_wait_is_narrated_rather_than_silent() -> None:
    """A long job that says nothing is indistinguishable from a dropped call."""
    import httpx

    from marvi_agent.tools import GatewayTools

    def done(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"status": "ok", "result": {"ok": True, "state": "done", "output": "ok"}}
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(done))
    context = FakeUpdates()
    await GatewayTools(client=client).await_delegated.__wrapped__(
        GatewayTools(client=client), context, "3f2a"
    )
    await client.aclose()

    assert context.fillers, "nothing fills the silence while the job runs"
    said, delay, interval = context.fillers[0]
    assert said.strip(), "the filler says nothing"
    # Sparse on purpose: this talks over a conversation that has moved on.
    assert delay >= 10 and (interval or 0) >= 60


async def test_a_job_that_is_not_there_is_an_error_not_a_wait() -> None:
    import httpx
    import pytest
    from livekit.agents import ToolError

    from marvi_agent.tools import GatewayTools

    def missing(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"status": "ok", "result": {"ok": False, "detail": "no job 'nope'"}}
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(missing))
    with pytest.raises(ToolError):
        await GatewayTools(client=client).await_delegated.__wrapped__(
            GatewayTools(client=client), FakeUpdates(), "nope"
        )
    await client.aclose()


def test_waiting_can_be_cancelled() -> None:
    """`ToolFlag.CANCELLABLE` is what makes the framework expose
    get_running_tasks and cancel_task to the model, so "stop that" works."""
    from livekit.agents.llm import ToolFlag

    from marvi_agent.tools import GatewayTools

    tool = GatewayTools().await_delegated

    assert ToolFlag.CANCELLABLE in tool.info.flags


def test_asking_twice_for_the_same_job_does_not_start_a_second_wait() -> None:
    """People repeat themselves when an answer is slow."""
    from marvi_agent.tools import GatewayTools

    tool = GatewayTools().await_delegated

    assert tool.info.on_duplicate == "reject"
    # By job id, not by name: waiting on a different job is a different thing.
    assert tool.info.duplicate_scope == "name_and_args"


# -- one confirmation at a time -----------------------------------------------


async def test_a_second_confirmation_cannot_displace_the_first() -> None:
    """One slot held one token, and a second sensitive call overwrote it.

    A spoken "yes" then approved whichever action arrived last, while the user
    believed they were approving the one they had just been told about. That is
    the confirmation flow doing the opposite of its job.
    """
    import httpx

    from marvi_agent.tools import GatewayTools

    def needs_confirmation(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, json={"status": "confirmation_required", "token": "tok-1"}
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(needs_confirmation))
    tools = GatewayTools(client=client)

    first = await tools._call("delegate_to_coder", {"task": "one"})
    held = tools.pending_token
    second = await tools._call("delegate_to_coder", {"task": "two"})
    await client.aclose()

    assert "needs confirmation" in first
    assert "already waiting" in second
    assert tools.pending_token == held, "the outstanding token was replaced"


async def test_an_expired_confirmation_does_not_block_the_next_one() -> None:
    """The Gateway drops a token after two minutes. If this went on holding the
    slot, one unanswered question would disable every sensitive tool for the
    rest of the session."""
    import httpx

    from marvi_agent.tools import CONFIRMATION_TTL, GatewayTools

    def needs_confirmation(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "confirmation_required", "token": "tok-2"})

    client = httpx.AsyncClient(transport=httpx.MockTransport(needs_confirmation))
    tools = GatewayTools(client=client)

    await tools._call("delegate_to_coder", {"task": "one"})
    tools._pending_at -= CONFIRMATION_TTL + 1
    answer = await tools._call("delegate_to_coder", {"task": "two"})
    await client.aclose()

    assert "needs confirmation" in answer


def test_updating_instructions_is_awaited() -> None:
    """It is a coroutine function whose signature says `-> None`.

    Checking the signature said "synchronous", so the call returned a coroutine
    nobody ran: every skill catalogue and every location block was silently
    discarded, with one RuntimeWarning per session as the only sign that the
    whole feature had never once worked.

    Asserted against the SDK rather than remembered, because the next release
    could make it either.
    """
    import inspect

    from livekit.agents import Agent

    from marvi_agent import session

    source = inspect.getsource(session)
    call = "agent.update_instructions("

    assert call in source
    if inspect.iscoroutinefunction(Agent.update_instructions):
        assert f"await {call}" in source, "update_instructions is async and is not awaited"


def test_the_worker_never_refuses_a_job_for_being_busy() -> None:
    """LiveKit marks a worker unavailable above 0.7 CPU load so a fleet can
    hand the job to a quieter machine. There is no quieter machine.

    This is one person's desktop and the only worker, so refusing does not move
    the work, it loses it: pressing Join opened a room that nothing ever
    joined. Speech recognition runs on the processor here by choice, which
    makes 0.7 normal rather than exceptional.
    """
    import math

    from marvi_agent.session import server

    threshold = server._load_threshold
    # It is a ServerEnvOption until the CLI resolves it, so take the value the
    # production path would see rather than the wrapper.
    value = getattr(threshold, "prod_default", threshold)

    assert math.isinf(value), f"a busy desktop would be refused jobs at {value}"


def test_an_optional_number_the_model_spelled_none_is_absent() -> None:
    """Asked to dim the light, the model filled the optional colour temperature
    in with the string "None". Pydantic refused it, the tool raised, LiveKit
    retried four times until `max_tool_steps` ran out, and the light never
    moved -- while Marvi said out loud that she would turn it down and then
    that she could not. An optional argument the model declined to use is not
    worth a turn."""
    from marvi_agent.tools import _number

    assert _number("None") is None
    assert _number("null") is None
    assert _number("") is None
    assert _number(None) is None
    assert _number(True) is None
    assert _number("40") == 40
    assert _number(40) == 40


def test_a_receipt_names_the_tool_and_what_it_was_given() -> None:
    """The fabrication outlived every rule written against it because the model
    had no record to check itself against. "I ran memory_forget to remove notes
    about your projects" was said on a turn where memory_forget had run four
    times -- for "Shreef", "Sharif", "Keychron K2" and "Keychron K10". Every
    word defensible, the whole of it false."""
    from marvi_agent.tools import receipt

    said = receipt("memory_forget", {"query": "Keychron K2"}, "ok", "removed 1")

    assert said == "[did memory_forget query=Keychron K2 -> ok] removed 1"


def test_a_failure_gets_a_receipt_too() -> None:
    """A tool that raised reached the model as a bare sentence with no subject,
    so "it failed" and "I did not try" were the same shape in the transcript."""
    from marvi_agent.tools import receipt

    said = receipt("room_set_light", {"on": True}, "FAILED", "the bridge is unreachable")

    assert said == "[did room_set_light on=True -> FAILED] the bridge is unreachable"


def test_a_receipt_survives_a_tool_that_takes_nothing() -> None:
    from marvi_agent.tools import receipt

    assert receipt("browser_close", {}, "ok") == "[did browser_close -> ok]"


def test_every_hand_written_tool_is_actually_registered() -> None:
    """`as_list` is written out by hand, and twice now a tool was added to the
    class and not to the list -- `forget` and the `tool_call` bridge both sat
    there decorated, described and unreachable.

    Nothing failed. The model simply could not see them: asked "Forget that I
    use Zed" it called `memory_unlink` and reported success, because among
    fifty-five tools there was no forget tool to find.
    """
    from marvi_agent.tools import GatewayTools

    gateway = GatewayTools()
    registered = {tool.info.name for tool in gateway.as_list()}
    written = {
        name
        for name in dir(GatewayTools)
        if not name.startswith("_") and hasattr(getattr(gateway, name, None), "info")
    }

    assert written - registered == set(), "decorated but never handed to the Agent"

@pytest.mark.asyncio
async def test_multi_step_desktop_and_browser_work_is_left_to_sub_agents() -> None:
    """Driving the desktop from the voice turn held the conversation for half
    a minute. Voice keeps the controls -- status, Stop, Private input, Resume,
    a one-shot open -- and hands the stepping to Jarvi and Talos."""
    names = [
        "computer_status", "computer_control", "computer_tools", "computer_action",
        "browser_status", "browser_control", "browser_open", "browser_action",
        "browser_read_image", "browser_save_download", "delegate",
    ]
    tools = ToolRegistry()
    for name in names:
        tools.register(ToolSpec(name=name, description=name, arguments={}, sensitive=False, handler=dict))
    app = create_app(version="0.1.0-test", tools=tools)
    other = GatewayTools(
        base_url="http://marvi.local",
        client=httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://marvi.local"),
    )

    async with other._client:
        await other.from_gateway(everything=True)

    loaded = set(other._catalogue)
    assert {"computer_status", "computer_control", "browser_status", "browser_control",
            "browser_open", "delegate"} <= loaded
    assert not loaded & {"computer_tools", "computer_action", "browser_action",
                         "browser_read_image", "browser_save_download"}


@pytest.mark.asyncio
async def test_a_delegated_job_is_followed_to_the_next_turn(monkeypatch) -> None:
    from marvi_agent import delegated

    tools = ToolRegistry()
    tools.register(
        ToolSpec(
            name="delegate",
            description="Hand a job to a sub-agent",
            arguments={"agent": str, "task": str},
            sensitive=False,
            handler=lambda agent, task: {"ok": True, "id": "abc123", "state": "running"},
        )
    )
    app = create_app(version="0.1.0-test", tools=tools)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://marvi.local")
    voice = GatewayTools(base_url="http://marvi.local", client=client)
    watched: list[str] = []
    monkeypatch.setattr(delegated.jobs, "watch", watched.append)

    async with client:
        await voice._run("delegate", {"agent": "jarvi", "task": "close notepad"})

    assert watched == ["abc123"]


@pytest.mark.asyncio
async def test_an_approved_delegation_is_followed_too(monkeypatch, tmp_path) -> None:
    """A Harvi fix job asks first. The job id arrives from the approval, not
    from the call -- and a job nobody follows is one whose report never comes."""
    from marvi_agent import delegated

    tools = ToolRegistry()
    tools.register(
        ToolSpec(
            name="delegate",
            description="Hand a job to a sub-agent",
            arguments={"agent": str, "task": str},
            optional={"mode": str},
            sensitive=True,
            handler=lambda agent, task, mode="": {"ok": True, "id": "fix42", "state": "running"},
        )
    )
    # Its own store: Confirm mode, whatever an earlier test left persisted.
    runtime = RuntimeStore(audit_path=tmp_path / "audit.jsonl")
    runtime.set_yolo(False)
    app = create_app(version="0.1.0-test", runtime=runtime, tools=tools)
    client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://marvi.local")
    voice = GatewayTools(base_url="http://marvi.local", client=client)
    watched: list[str] = []
    monkeypatch.setattr(delegated.jobs, "watch", watched.append)

    async with client:
        asked = await voice._run("delegate", {"agent": "harvi", "task": "fix it", "mode": "fix"})
        assert "needs confirmation" in asked and watched == []
        await voice.approve_pending_action.__wrapped__(voice, None)

    assert watched == ["fix42"]


@pytest.mark.asyncio
async def test_computer_tools_reach_the_voice_bridge(gateway, voice, monkeypatch):
    client, _, _ = gateway
    monkeypatch.setenv('MARVI_LOCAL_TOKEN', 'voice-computer-fixture')
    client.headers['x-marvi-local'] = 'voice-computer-fixture'
    async with client:
        result = await voice._call('computer_status', {})
    assert 'cua-driver' in result
