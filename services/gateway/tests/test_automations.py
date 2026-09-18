"""When X happens, do Y -- and the rules about what that may not become."""

from __future__ import annotations

import pytest
from httpx import ASGITransport, AsyncClient

from marvi_gateway.automations import MAX_PER_HOUR, Automations, fill, matches


def _rules(tmp_path, calls: list | None = None) -> Automations:
    rules = Automations(tmp_path / "automations.db")
    if calls is not None:
        rules.call = lambda name, arguments: calls.append((name, arguments)) or {"status": "executed"}
    return rules


def test_a_rule_fires_only_on_what_it_was_written_for(tmp_path) -> None:
    calls: list = []
    rules = _rules(tmp_path, calls)
    rules.add(
        "Warm light when I sit down after six",
        "room",
        "room_set_light",
        {"state": "warm"},
        {"kind": "presence", "who": "owner"},
        enabled=True,
    )

    rules.fire("room", {"kind": "presence", "who": "owner"})
    rules.fire("room", {"kind": "presence", "who": "someone else"})  # condition fails
    rules.fire("account", {"kind": "presence", "who": "owner"})  # wrong trigger

    assert calls == [("room_set_light", {"state": "warm"})]


def test_a_disabled_rule_does_nothing(tmp_path) -> None:
    calls: list = []
    rules = _rules(tmp_path, calls)
    rule = rules.add("Off by default", "room", "room_set_light", {"state": "warm"})

    assert rule["enabled"] is False
    rules.fire("room", {})
    assert calls == []

    rules.set_enabled(rule["id"], True)
    rules.fire("room", {})
    assert calls == [("room_set_light", {"state": "warm"})]


def test_marvi_cannot_switch_on_a_rule_she_proposed(tmp_path) -> None:
    """A model that can write its own standing instructions can grant itself
    anything. She proposes; the user enables."""
    rules = _rules(tmp_path, [])
    proposed = rules.add(
        "Every time you do that", "room", "room_set_light", enabled=True, proposed_by="marvi"
    )

    assert proposed["enabled"] is False
    assert proposed["proposed_by"] == "marvi"


def test_the_payload_fills_declared_fields_and_never_becomes_one() -> None:
    filled = fill({"message": "Build {status} for {branch}", "to": "owner"},
                  {"status": "failed", "branch": "main"})

    assert filled["message"] == "Build failed for main"
    assert filled["to"] == "owner"  # untouched
    # A field the rule never mentioned cannot add an argument.
    assert "tool" not in fill({"message": "hi"}, {"tool": "send_email"})


def test_a_condition_is_plain_matching_with_no_model(tmp_path) -> None:
    assert matches({"match": '{"kind": "mail"}'}, {"kind": "mail"}) is True
    assert matches({"match": '{"kind": "mail"}'}, {"kind": "room"}) is False
    # A list is any-of; a string is a substring, case-insensitively.
    assert matches({"match": '{"who": ["owner", "guest"]}'}, {"who": "guest"}) is True
    assert matches({"match": '{"subject": "invoice"}'}, {"subject": "Your INVOICE is due"}) is True
    assert matches({"match": "not json"}, {"kind": "mail"}) is False


def test_a_runaway_trigger_is_rate_limited(tmp_path) -> None:
    calls: list = []
    rules = _rules(tmp_path, calls)
    rules.add("Chatty", "webhook", "room_set_light", enabled=True)

    for _ in range(MAX_PER_HOUR + 5):
        rules.fire("webhook", {})

    assert len(calls) == MAX_PER_HOUR
    assert any("rate limited" in str(row) for row in rules.all()[0]["history"])


def test_a_webhook_needs_its_own_secret(tmp_path) -> None:
    rules = _rules(tmp_path, [])
    hook = rules.add("From a script", "webhook", "room_set_light", enabled=True)

    assert hook["secret"], "a webhook rule has a secret"
    assert rules.by_secret(hook["id"], hook["secret"]) is not None
    assert rules.by_secret(hook["id"], "guessed") is None
    assert rules.by_secret("nope", hook["secret"]) is None

    # A rule that is not a webhook has no secret and cannot be poked.
    other = rules.add("Not a hook", "room", "room_set_light", enabled=True)
    assert rules.by_secret(other["id"], "") is None


def test_what_happened_is_kept(tmp_path) -> None:
    rules = _rules(tmp_path)
    rules.call = lambda name, arguments: (_ for _ in ()).throw(RuntimeError("the light is off"))
    rule = rules.add("Will fail", "room", "room_set_light", enabled=True)

    rules.fire("room", {})

    after = rules.get(rule["id"])
    assert after["runs"] == 1
    assert after["history"][0]["ok"] == 0
    assert "the light is off" in after["history"][0]["detail"]


@pytest.mark.asyncio
async def test_an_action_goes_through_confirmation_like_any_tool(monkeypatch, tmp_path) -> None:
    """The rule that matters: an automation asks for a tool call, it does not
    get a private way to make one."""
    from marvi_gateway.app import create_app

    monkeypatch.setenv("MARVI_HOME", str(tmp_path))
    monkeypatch.delenv("MARVI_YOLO", raising=False)
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        made = await client.post(
            "/automations",
            json={
                "name": "Write a file when poked",
                "trigger": "webhook",
                "action": "file_write",
                "arguments": {"path": "poked.txt", "content": "{who} was here"},
                "enabled": True,
            },
        )
        rule = made.json()
        assert rule["enabled"] is True

        fired = await client.post(
            f"/hooks/{rule['id']}",
            json={"who": "a script"},
            headers={"x-marvi-secret": rule["secret"]},
        )
        # `file_write` is sensitive, so it waits for the user rather than
        # writing because a webhook said so.
        assert fired.status_code == 200
        assert "confirmation_required" in str(fired.json())

        refused = await client.post(f"/hooks/{rule['id']}", json={}, headers={"x-marvi-secret": "no"})
        assert refused.status_code == 404
