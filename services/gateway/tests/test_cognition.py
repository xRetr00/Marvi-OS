"""The unattended Mind/Memory harness gets context and only bounded reads."""

from __future__ import annotations

from marvi_gateway import distil
from marvi_gateway.cognition import MAX_TOOL_CALLS_PER_ROUND, MIND_TOOLS, CognitionHarness
from marvi_gateway.identity import IdentityFiles
from marvi_gateway.providers import Completion, Usage
from marvi_gateway.tools import ToolRegistry, ToolSpec


class SequencedClient:
    def __init__(self, replies: list[Completion]) -> None:
        self.replies = replies
        self.calls: list[tuple[list[dict], dict]] = []

    def call_with_fallback(self, messages, **kwargs):
        self.calls.append((messages, kwargs))
        return self.replies.pop(0)


def completion(text: str, *, calls: list[dict] | None = None) -> Completion:
    return Completion(
        text=text,
        usage=Usage(input=10, output=5),
        provider="openai",
        model="aux-model",
        tool_calls=calls or [],
    )


def identity_at(tmp_path) -> IdentityFiles:
    identity = IdentityFiles(tmp_path / "identity")
    identity.write_soul("Be precise and calm.")
    identity.write_user("The owner is Ada.")
    return identity


def test_mind_gets_identity_time_aux_route_and_a_bounded_read_tool(tmp_path, monkeypatch) -> None:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="web_search",
            description="Search the web",
            arguments={"query": str},
            sensitive=False,
            handler=lambda query: {"result": f"found {query}"},
        )
    )
    # Even a name on the allowlist is excluded if its declaration can act.
    registry.register(
        ToolSpec(
            name="file_read",
            description="Pretend write",
            arguments={"path": str},
            sensitive=True,
            handler=lambda path: path,
        )
    )
    client = SequencedClient(
        [
            completion(
                "",
                calls=[
                    {
                        "id": "search-1",
                        "name": "web_search",
                        "arguments": {"query": "current train status"},
                    }
                ],
            ),
            completion('{"worth_it": false, "say": ""}'),
        ]
    )
    monkeypatch.setenv("MARVI_AUX_MIND", "openai/aux-model")

    result = CognitionHarness(client, identity_at(tmp_path), registry).ask(
        "mind", "Decide whether to speak.", "A train may be late.", 120, MIND_TOOLS
    )

    first_messages, first_options = client.calls[0]
    system = first_messages[0]["content"]
    assert "Be precise and calm." in system
    assert "The owner is Ada." in system
    assert "Local date:" in system and "Local time:" in system
    assert "skills" not in system.lower()
    assert first_options["job"] == "aux"
    assert first_options["preferred"] == "openai"
    assert first_options["model"] == "aux-model"
    assert [tool["name"] for tool in first_options["tools"]] == ["web_search"]
    assert "EXTERNAL DATA" in client.calls[1][0][-1]["content"]
    assert result.tools_used == ("web_search",)
    assert result.usage.billable == 30


def test_memory_reflection_uses_the_same_identity_harness_and_recall(tmp_path) -> None:
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="memory_recall",
            description="Recall memory",
            arguments={"query": str},
            sensitive=False,
            handler=lambda query: {"results": [{"body": "Ada prefers quiet mornings."}]},
        )
    )
    client = SequencedClient(
        [
            completion(
                "",
                calls=[
                    {
                        "id": "memory-1",
                        "name": "memory_recall",
                        "arguments": {"query": "morning preference"},
                    }
                ],
            ),
            completion("morning preference :: Ada prefers quiet mornings."),
        ]
    )
    harness = CognitionHarness(client, identity_at(tmp_path), registry)

    result = distil.summarise_memories(
        harness, [{"subject": "morning preference", "count": 4}]
    )

    assert result == [("morning preference", "Ada prefers quiet mornings.")]
    assert "The owner is Ada." in client.calls[0][0][0]["content"]
    assert client.calls[0][1]["job"] == "aux"
    offered = [tool["name"] for tool in client.calls[0][1]["tools"]]
    assert offered == ["memory_recall"]


def test_one_model_turn_cannot_fan_out_unbounded_reads(tmp_path) -> None:
    seen = []
    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="web_search",
            description="Search",
            arguments={"query": str},
            sensitive=False,
            handler=lambda query: seen.append(query) or {"ok": True},
        )
    )
    calls = [
        {"id": f"call-{index}", "name": "web_search", "arguments": {"query": str(index)}}
        for index in range(MAX_TOOL_CALLS_PER_ROUND + 3)
    ]
    client = SequencedClient([completion("", calls=calls), completion("done")])

    result = CognitionHarness(client, identity_at(tmp_path), registry).ask(
        "mind", "Check facts.", "Something changed.", 100, ("web_search",)
    )

    assert len(seen) == MAX_TOOL_CALLS_PER_ROUND
    assert len(result.tools_used) == MAX_TOOL_CALLS_PER_ROUND
