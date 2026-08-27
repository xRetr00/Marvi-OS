"""Credentials: asked for through the screen, read only when opted into.

Two rules hold this together and both are load-bearing:

* the value the user types never reaches the model. `ask_secret` returns the
  fact that it asked; the desktop sends the value straight to the settings
  store; Marvi is told the name. That is the pattern every published guide on
  agent secret handling converges on, and the difference between it and "she
  asked and you told her" is the difference between a key on your machine and a
  key in somebody's inference logs.
* reading a credential file is a setting rather than a block, because refusing
  outright made her useless for setting things up -- and `masked` exists
  because "is my key set" and "what is my key" look like the same question and
  are not.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from marvi_gateway.app import create_app
from marvi_gateway.credentials import (
    FULL,
    MASKED,
    OFF,
    SETTING,
    level,
    mask,
    mask_text,
    register_secret_tool,
)
from marvi_gateway.filepolicy import GENERAL, READ_SETTING, ROOT_SETTING, Access, PathRefusedError
from marvi_gateway.runtime import RuntimeStore

# -- reading a file with secrets in it ---------------------------------------


@pytest.fixture
def env_file(tmp_path, monkeypatch):
    monkeypatch.setenv(ROOT_SETTING, str(tmp_path))
    monkeypatch.setenv(READ_SETTING, GENERAL)
    monkeypatch.delenv(SETTING, raising=False)
    (tmp_path / ".env").write_text(
        "# providers\nOPENROUTER_API_KEY=sk-or-v1-abcdefghijklmnop\nEMPTY=\n", encoding="utf-8"
    )
    return tmp_path / ".env"


def test_off_is_the_default_and_refuses(env_file) -> None:
    assert level() == OFF
    with pytest.raises(PathRefusedError, match="Settings > Workspace"):
        Access.from_env().resolve(".env", write=False)


def test_masked_lets_her_read_it(env_file, monkeypatch) -> None:
    monkeypatch.setenv(SETTING, MASKED)

    assert Access.from_env().resolve(".env", write=False) == env_file.resolve()


def test_writing_a_credential_file_is_refused_at_every_level(env_file, monkeypatch) -> None:
    """`ask_secret` is how a credential gets set, and it is a better way: the
    value never passes through the model."""
    monkeypatch.setenv(SETTING, FULL)
    monkeypatch.setenv("MARVI_FILE_WRITE_SCOPE", GENERAL)

    with pytest.raises(PathRefusedError, match="ask_secret"):
        Access.from_env().resolve(".env", write=True)


def test_the_read_tool_masks_the_values(env_file, monkeypatch) -> None:
    from marvi_gateway.workspace import Workspace

    monkeypatch.setenv(SETTING, MASKED)
    found = Workspace().read(".env")

    assert "OPENROUTER_API_KEY=" in found["text"]
    assert "abcdefghijklmnop" not in found["text"]
    assert found["masked"]


def test_full_returns_the_real_thing(env_file, monkeypatch) -> None:
    from marvi_gateway.workspace import Workspace

    monkeypatch.setenv(SETTING, FULL)
    found = Workspace().read(".env")

    assert "sk-or-v1-abcdefghijklmnop" in found["text"]
    assert "masked" not in found


# -- masking -----------------------------------------------------------------


def test_masking_keeps_enough_to_recognise_and_not_enough_to_use() -> None:
    masked = mask("sk-or-v1-abcdefghijklmnop")

    assert masked.startswith("sk-or-")
    assert "abcdefghijklmnop" not in masked


def test_a_short_value_gives_nothing_away() -> None:
    assert set(mask("hunter2")) <= {"*", "h", "u", "n", "t", "e", "r", "2"}
    assert mask("abc") == "***"


def test_masking_keeps_the_shape_of_the_file() -> None:
    """The shape is the point: which names are there, which are empty, what
    order they are in. That is what somebody debugging a configuration needs."""
    text = mask_text("# a comment\nAPI_KEY=supersecretvalue\nEMPTY=\nexport OTHER=alsosecret\n")

    assert "# a comment" in text
    assert "API_KEY=" in text
    assert "EMPTY=" in text
    assert "supersecret" not in text
    assert "alsosecret" not in text


def test_masking_handles_credential_json() -> None:
    text = mask_text('{\n  "client_secret": "abcdefghijklmnop"\n}')

    assert '"client_secret"' in text
    assert "abcdefghijklmnop" not in text


def test_an_empty_value_stays_empty_rather_than_becoming_stars() -> None:
    """"set to something I cannot show you" and "not set" are different
    answers, and masking must not turn the second into the first."""
    assert mask_text("EMPTY=\n") == "EMPTY="


# -- asking for one ----------------------------------------------------------


def tool_for(store: RuntimeStore):
    registered: dict = {}

    class Registry:
        def register(self, spec) -> None:
            registered[spec.name] = spec

    register_secret_tool(Registry(), store)
    return registered["ask_secret"]


def test_asking_never_returns_a_value(tmp_path) -> None:
    store = RuntimeStore(audit_path=tmp_path / "audit.jsonl")

    result = tool_for(store).handler(name="openrouter_api_key", why="to reach the model")

    assert result == {
        "asked": True,
        "name": "OPENROUTER_API_KEY",
        "note": result["note"],
    }
    assert "never" in result["note"]


def test_the_field_goes_on_screen_with_its_reason(tmp_path) -> None:
    """The user is about to type a credential into a box and is owed a reason."""
    store = RuntimeStore(audit_path=tmp_path / "audit.jsonl")

    tool_for(store).handler(name="SMTP_PASSWORD", why="to send the email you asked for")

    assert store.assistant.secret.name == "SMTP_PASSWORD"
    assert "send the email" in store.assistant.secret.why


def test_a_name_that_is_not_a_setting_name_is_refused(tmp_path) -> None:
    """Otherwise this is a way to write anywhere in the settings store from a
    sentence."""
    store = RuntimeStore(audit_path=tmp_path / "audit.jsonl")

    assert tool_for(store).handler(name="../../etc/passwd")["asked"] is False
    assert store.assistant.secret is None


def test_saving_stores_it_and_never_echoes_it(monkeypatch) -> None:
    with TestClient(create_app()) as client:
        client.post(
            "/tools/ask_secret", json={"arguments": {"name": "TEST_TOKEN", "why": "a test"}}
        )
        asked = client.get("/runtime").json()["assistant"]["secret"]
        assert asked["name"] == "TEST_TOKEN"

        saved = client.post(
            "/voice/secret",
            json={"id": asked["id"], "name": "TEST_TOKEN", "value": "hunter2-secret"},
        ).json()
        after = client.get("/runtime").json()

    assert saved == {"stored": True, "name": "TEST_TOKEN"}
    assert "hunter2" not in str(after), "the value must not ride back on the runtime"
    assert after["assistant"]["secret"] is None


def test_dismissing_the_field_is_not_an_error() -> None:
    """"I would rather do this myself" is a real answer."""
    with TestClient(create_app()) as client:
        client.post("/tools/ask_secret", json={"arguments": {"name": "TEST_TOKEN"}})
        asked = client.get("/runtime").json()["assistant"]["secret"]

        saved = client.post(
            "/voice/secret", json={"id": asked["id"], "name": "TEST_TOKEN", "value": ""}
        ).json()

    assert saved["stored"] is False


def test_the_audit_records_the_name_and_not_the_value(tmp_path, monkeypatch) -> None:
    """An audit trail exists to be read; a value in it is a value on disk in
    plain text, in a second place."""
    with TestClient(create_app()) as client:
        client.post("/tools/ask_secret", json={"arguments": {"name": "TEST_TOKEN"}})
        asked = client.get("/runtime").json()["assistant"]["secret"]
        client.post(
            "/voice/secret",
            json={"id": asked["id"], "name": "TEST_TOKEN", "value": "hunter2-secret"},
        )
        events = client.get("/audit?limit=20").json()["events"]

    assert "hunter2" not in str(events)
    assert any(event["tool"] == "ask_secret" for event in events)
