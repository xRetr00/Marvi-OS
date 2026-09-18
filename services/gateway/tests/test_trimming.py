"""Keeping one tool result from eating the conversation."""

from __future__ import annotations

import re

from marvi_gateway import trimming
from marvi_gateway.tools import ToolRegistry, ToolSpec


def _handle(text: str) -> str:
    found = re.search(r'handle="([^"]+)"', text)
    assert found, text[-200:]
    return found.group(1)


def test_a_huge_result_is_shortened_and_the_rest_is_readable() -> None:
    whole = "".join(f"line {n}\n" for n in range(4000))
    trimmed, cut = trimming.apply("web_fetch", {"text": whole}, ceiling=2_000)

    assert cut > 0 and len(trimmed["text"]) < len(whole)
    assert "more characters" in trimmed["text"]

    rest = trimming.more(_handle(trimmed["text"]), offset=2_000)
    assert rest["from"] == 2_000 and rest["of"] == len(whole)
    assert whole[2_000:2_100] in rest["text"]

    # Reading to the end says so rather than looping forever.
    end = trimming.more(_handle(trimmed["text"]), offset=len(whole) - 10)
    assert end["more"] is False


def test_the_shape_survives_so_widgets_and_drivers_still_work() -> None:
    result = {
        "text": "x" * 50_000,
        "ok": True,
        "count": 3,
        "sources": [{"url": "https://example.com", "title": "A page"}],
    }
    trimmed, cut = trimming.apply("web_search", result, ceiling=1_000)

    assert cut > 0
    assert trimmed["ok"] is True and trimmed["count"] == 3
    # The nesting a widget reads is untouched.
    assert trimmed["sources"] == result["sources"]


def test_the_budget_is_shared_rather_than_per_field() -> None:
    result = {"a": "x" * 9_000, "b": "y" * 9_000, "c": "z" * 9_000}
    trimmed, _cut = trimming.apply("file_read", result, ceiling=3_000)

    kept = sum(len(value) for value in trimmed.values())
    # Three fields, one budget -- plus the notices saying where the rest went.
    assert kept < 3_000 + 3 * 200


def test_what_marvis_own_code_parses_is_never_trimmed() -> None:
    result = {"state": "x" * 40_000}
    for tool in ("browser_action", "computer_status", "present_widget", "delegate", "room_state"):
        assert trimming.apply(tool, result, ceiling=100) == (result, 0)
    assert trimming.trimmable("web_search") is True


def test_a_small_result_is_returned_exactly_as_it_was() -> None:
    result = {"text": "short", "n": 1}
    assert trimming.apply("web_fetch", result) == (result, 0)
    assert trimming.apply("web_fetch", "a string") == ("a string", 0)
    # A result that will not serialise is left alone rather than mangled.
    unserialisable = {"thing": object()}
    assert trimming.apply("web_fetch", unserialisable, ceiling=1)[1] == 0


def test_the_cap_can_be_turned_off(monkeypatch) -> None:
    monkeypatch.setenv(trimming.SETTING, "0")
    assert trimming.apply("web_fetch", {"text": "x" * 80_000})[1] == 0
    monkeypatch.setenv(trimming.SETTING, "nonsense")
    assert trimming.cap() == trimming.DEFAULT_CAP


def test_a_stale_handle_says_so_rather_than_failing() -> None:
    answer = trimming.more("nothing-like-this", 0)
    assert "no longer available" in answer["error"]


def test_the_router_trims_and_the_tool_reads_the_rest(monkeypatch) -> None:
    monkeypatch.setenv(trimming.SETTING, "1500")
    registry = ToolRegistry()
    registry.register(
        ToolSpec("web_fetch", "Fetch a page for the test.", {}, False, lambda: {"text": "y" * 9_000})
    )
    trimming.register_more_tool(registry)

    result = registry.execute(registry.get("web_fetch"), {})
    assert len(result["text"]) < 9_000

    spec = registry.get("tool_more")
    rest = registry.execute(spec, registry.validate(spec, {"handle": _handle(result["text"])}))
    assert rest["of"] == 9_000 and rest["text"].startswith("y")
