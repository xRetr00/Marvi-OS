"""What an auxiliary call actually sends, and to which model.

Every auxiliary call on this machine failed for a day and nothing said so.
Three separate reasons, each of which looked like "the model had nothing to
say" from the outside -- which is a normal outcome for all of these jobs, so
they carried on quietly with the deterministic fallback.
"""

from __future__ import annotations

import pytest

from marvi_gateway import auxiliary
from marvi_gateway.providers import openrouter
from marvi_gateway.providers.metered import openrouter as openrouter_profile


def test_the_default_auxiliary_model_exists() -> None:
    """`google/gemini-3-flash` was hardcoded and has never existed. OpenRouter
    answers "not a valid model ID" with a 400, so memory extraction, skill
    proposals, dreaming, titles and the background mind all failed.

    Checked by shape rather than against the live catalog -- a test that calls
    an API fails when the network does -- but the value itself was verified
    against `GET /api/v1/models` when it was changed.
    """
    assert openrouter_profile.default_aux_model.startswith("google/gemini-3.")


def test_upstream_pinning_does_not_follow_a_different_model(monkeypatch) -> None:
    """`coreweave/fp8` is an endpoint of one model, not a provider preference.

    It was sent on every job, so an auxiliary call for a different model went
    out pinned to an upstream that has never served it, and OpenRouter refused
    the request.
    """
    monkeypatch.setenv("MARVI_OPENROUTER_PROVIDERS", "coreweave/fp8")
    monkeypatch.setenv("MARVI_OPENROUTER_MODEL", "deepseek/deepseek-v4-flash-0731")

    # The model they were chosen for keeps them, whatever the job -- voice and
    # chat both run it, and so does an auxiliary role left on auto.
    assert openrouter.route_for("main").order == ("coreweave/fp8",)
    assert openrouter.route_for("voice").order == ("coreweave/fp8",)
    assert openrouter.route_for("aux", "deepseek/deepseek-v4-flash-0731").order == (
        "coreweave/fp8",
    )
    # A different model does not.
    assert openrouter.route_for("aux", "google/gemini-3.5-flash-lite").order == ()


def test_the_routing_policy_still_travels(monkeypatch) -> None:
    """A preference for the fastest upstream is about the request, not the
    model, so it applies wherever the request goes."""
    monkeypatch.setenv("MARVI_OPENROUTER_ROUTE", "fastest")
    monkeypatch.delenv("MARVI_OPENROUTER_PROVIDERS", raising=False)

    assert openrouter.route_for("aux", "google/gemini-3.5-flash-lite").as_body() == {
        "sort": "latency"
    }


def test_pinning_off_a_pin_does_not_forbid_fallback(monkeypatch) -> None:
    """`allow_fallbacks=False` means "this upstream or nothing". With no order
    to pin to, that is a request that can only fail."""
    monkeypatch.setenv("MARVI_OPENROUTER_PIN", "true")
    monkeypatch.setenv("MARVI_OPENROUTER_PROVIDERS", "coreweave/fp8")
    monkeypatch.setenv("MARVI_OPENROUTER_MODEL", "deepseek/deepseek-v4-flash-0731")

    assert openrouter.route_for("main").allow_fallbacks is False
    assert openrouter.route_for("aux", "google/gemini-3.5-flash-lite").allow_fallbacks is True


# -- the effort a role asks for ------------------------------------------------


def test_a_role_can_name_its_own_reasoning_effort(monkeypatch) -> None:
    monkeypatch.setenv("MARVI_AUX_MEMORY", "openrouter/google/gemini-3.5-flash")
    monkeypatch.setenv("MARVI_AUX_MEMORY_EFFORT", "low")

    assert auxiliary.fallback_overrides("memory") == {
        "preferred": "openrouter",
        "model": "google/gemini-3.5-flash",
        "effort": "low",
    }


def test_an_effort_left_behind_does_not_apply_to_the_main_model(monkeypatch) -> None:
    """Set an effort on a role, then put the role back to auto. The effort is
    still in the file, and without this it would start governing the main
    model's calls -- a setting nobody chose, on a model nobody pointed it at."""
    monkeypatch.delenv("MARVI_AUX_MEMORY", raising=False)
    monkeypatch.setenv("MARVI_AUX_MEMORY_EFFORT", "high")

    assert auxiliary.effort("memory") == ""
    assert auxiliary.fallback_overrides("memory") == {}


def test_the_settings_page_is_told_the_effort_and_where_to_write_it(monkeypatch) -> None:
    monkeypatch.setenv("MARVI_AUX_VOICE", "openrouter/google/gemini-3.5-flash")
    monkeypatch.setenv("MARVI_AUX_VOICE_EFFORT", "low")

    role = next(row for row in auxiliary.status()["roles"] if row["key"] == "voice")

    assert role["effort"] == "low"
    assert role["effort_setting"] == "MARVI_AUX_VOICE_EFFORT"


# -- a model that will not have reasoning turned off ---------------------------


class Response:
    def __init__(self, status: int, text: str) -> None:
        self.status_code = status
        self.text = text
        self.headers: dict[str, str] = {}

    def json(self) -> dict:
        return {"choices": [{"message": {"content": "ok"}}], "usage": {}}

    def raise_for_status(self) -> None:
        return None


@pytest.mark.parametrize(
    ("body", "expected"),
    [
        ("Reasoning is mandatory for this endpoint and cannot be disabled.", True),
        ("reasoning cannot be disabled", True),
        ("model not found", False),
        ("your reasoning_effort value is invalid", False),
    ],
)
def test_only_the_refusal_a_retry_fixes_is_retried(body: str, expected: bool) -> None:
    """Narrow on purpose. Every other 400 is ours to fix, and retrying one
    would hide the thing that needs fixing -- which is how an invalid model id
    stayed invisible for a day."""
    from marvi_gateway.providers.client import ProviderClient

    assert ProviderClient._reasoning_is_mandatory(Response(400, body)) is expected
