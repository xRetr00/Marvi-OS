"""Which model does which job.

The interesting properties are not "does a setting round-trip". They are:
does an unset role change anything, does a typo stop Marvi thinking, and can a
role hand the voice path a provider it cannot call.
"""

from __future__ import annotations

from marvi_gateway import auxiliary


def test_an_unset_role_changes_nothing(monkeypatch) -> None:
    """Auto is the default and it is what happened before this existed. A role
    nobody has touched must add no argument to the call."""
    for role in auxiliary.ROLES:
        monkeypatch.delenv(role.setting, raising=False)

    assert auxiliary.overrides("mind") == {}
    assert auxiliary.resolve("voice") == ("", "")


def test_a_role_names_a_provider_and_a_model(monkeypatch) -> None:
    monkeypatch.setenv("MARVI_AUX_MIND", "openrouter/deepseek/deepseek-v4-flash-0731")

    assert auxiliary.overrides("mind") == {
        "provider": "openrouter",
        # The model may contain the separator; only the first one splits.
        "model": "deepseek/deepseek-v4-flash-0731",
    }


def test_a_typo_falls_back_rather_than_raising(monkeypatch) -> None:
    """This sits on the path of every background call. A malformed settings
    field must not be able to stop the mind."""
    for bad in ("nonsense", "openrouter/", "/a-model", "   "):
        monkeypatch.setenv("MARVI_AUX_MIND", bad)
        assert auxiliary.overrides("mind") == {}, bad


def test_only_roles_with_somewhere_to_plug_in_are_offered() -> None:
    """A setting for a call that is never made reads as a knob, does nothing,
    and teaches people the page is decorative.

    Memory, web reading and titles are all good candidates and not one of them
    calls a model today, so they are named as not-yet rather than shipped.
    """
    offered = {role.key for role in auxiliary.ROLES}

    assert offered == {"voice", "vision", "mind"}
    assert not offered & set(auxiliary.NOT_YET)


def test_an_unknown_role_is_auto_rather_than_an_error() -> None:
    assert auxiliary.overrides("no-such-role") == {}


def test_the_status_says_what_each_role_resolves_to(monkeypatch) -> None:
    monkeypatch.delenv("MARVI_AUX_VOICE", raising=False)
    monkeypatch.setenv("MARVI_AUX_MIND", "openai/gpt-5-mini")

    rows = {row["key"]: row for row in auxiliary.status()["roles"]}

    assert rows["voice"]["auto"] is True
    assert rows["mind"]["auto"] is False
    assert rows["mind"]["model"] == "gpt-5-mini"
    assert rows["mind"]["setting"] == "MARVI_AUX_MIND"
