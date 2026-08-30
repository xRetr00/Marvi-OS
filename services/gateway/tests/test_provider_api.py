"""The providers and identity surfaces the control center talks to.

Two things are being protected here. Provider settings must be editable from
the GUI without a rebuild, which is the whole reason a saved-settings file
exists at all. And a credential typed into that GUI must never come back out of
it.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from marvi_gateway.app import create_app
from marvi_gateway.providers import config
from marvi_gateway.tools import ToolRegistry


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("MARVI_PROVIDER_CONFIG", str(tmp_path / "providers.env"))
    monkeypatch.setenv("MARVI_IDENTITY_DIR", str(tmp_path / "identity"))
    monkeypatch.setenv("MARVI_TOKEN_STORE", str(tmp_path / "tokens.bin"))
    monkeypatch.delenv("MARVI_CODEX_CLIENT_ID", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("MARVI_PROVIDER", raising=False)
    with TestClient(create_app(tools=ToolRegistry())) as c:
        yield c


# -- the settings file ------------------------------------------------------


def test_saved_settings_become_environment_variables(tmp_path, monkeypatch) -> None:
    path = tmp_path / "providers.env"
    config.write({"OPENAI_API_KEY": "sk-saved", "MARVI_OLLAMA_MODEL": "llama4"}, path)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("MARVI_OLLAMA_MODEL", raising=False)

    assert config.load_into_environ(path) == 2
    import os

    assert os.environ["OPENAI_API_KEY"] == "sk-saved"


def test_a_real_environment_variable_wins(tmp_path, monkeypatch) -> None:
    path = tmp_path / "providers.env"
    config.write({"OPENAI_API_KEY": "sk-saved"}, path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-shell")
    config.load_into_environ(path)

    # A stale saved value must not quietly override what the user launched with.
    import os

    assert os.environ["OPENAI_API_KEY"] == "sk-from-shell"


def test_secrets_are_masked_on_the_way_out(tmp_path) -> None:
    path = tmp_path / "providers.env"
    config.write({"OPENAI_API_KEY": "sk-abcdef123456", "MARVI_OLLAMA_MODEL": "llama4"}, path)
    shown = config.visible(path)

    assert "abcdef" not in shown["OPENAI_API_KEY"]
    assert shown["MARVI_OLLAMA_MODEL"] == "llama4"  # not a secret, shown plainly


def test_an_empty_value_disconnects(tmp_path, monkeypatch) -> None:
    path = tmp_path / "providers.env"
    monkeypatch.setenv("MARVI_PROVIDER_CONFIG", str(path))
    config.update({"OPENAI_API_KEY": "sk-x"}, path)
    config.update({"OPENAI_API_KEY": ""}, path)

    import os

    assert config.read(path)["OPENAI_API_KEY"] == ""
    assert not os.environ.get("OPENAI_API_KEY")


def test_disconnect_survives_restart_with_an_inherited_openai_key(tmp_path, monkeypatch) -> None:
    path = tmp_path / "providers.env"
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-parent-process")

    config.update({"OPENAI_API_KEY": ""}, path)
    monkeypatch.setenv("OPENAI_API_KEY", "sk-from-parent-process")
    config.load_into_environ(path)

    import os

    assert config.read(path)["OPENAI_API_KEY"] == ""
    assert "OPENAI_API_KEY" not in os.environ


# -- the page ---------------------------------------------------------------


def test_the_page_lists_every_provider_with_its_billing(client) -> None:
    body = client.get("/providers").json()
    rows = {p["name"]: p for p in body["providers"]}

    assert rows["ollama"]["access_path"] == "local"
    assert rows["opencode-go"]["limits"]["style"] == "rolling_windows"
    assert rows["anthropic"]["api_mode"] == "anthropic"
    assert body["totals"]["billable"] == 0


def test_usage_is_a_dedicated_durable_page(client) -> None:
    recorded = client.post(
        "/usage", json={"provider": "openai", "input": 100, "output": 20, "cached_input": 80}
    )
    body = client.get("/usage?refresh=false").json()

    assert recorded.json() == {"recorded": True}
    assert body["totals"]["billable"] == 40
    assert (
        next(row for row in body["providers"] if row["name"] == "openai")["usage"]["input"] == 100
    )


def test_usage_rejects_unknown_provider(client) -> None:
    assert client.post("/usage", json={"provider": "made-up", "input": 10}).status_code == 400


def test_plan_providers_carry_the_terms_warning(client) -> None:
    rows = {p["name"]: p for p in client.get("/providers").json()["providers"]}

    assert "suspension" in rows["codex"]["warning"]
    assert rows["openai"]["warning"] is None


def test_connecting_a_provider_takes_effect_without_a_restart(client) -> None:
    before = {p["name"]: p for p in client.get("/providers").json()["providers"]}
    assert before["openai"]["configured"] is False

    body = client.put(
        "/providers/settings", json={"values": {"OPENAI_API_KEY": "sk-typed-in-the-gui"}}
    ).json()
    after = {p["name"]: p for p in body["providers"]}

    assert after["openai"]["configured"] is True
    # The key must not come back out of the surface it was typed into.
    assert "sk-typed-in-the-gui" not in str(body)


def test_the_registry_reports_the_variables_it_reads(client) -> None:
    rows = {p["name"]: p for p in client.get("/providers").json()["providers"]}

    # The GUI must not derive env names from the provider name; OpenCode Go and
    # llama.cpp both break that guess.
    assert rows["opencode-go"]["env"]["key"] == "OPENCODE_GO_API_KEY"
    assert rows["llamacpp"]["env"]["model"] == "MARVI_LOCAL_OPENAI_MODEL"
    assert rows["ollama"]["env"]["key"] == ""  # no credential to ask for


def test_the_model_is_editable_per_provider(client) -> None:
    body = client.put(
        "/providers/settings", json={"values": {"MARVI_OLLAMA_MODEL": "qwen3:8b"}}
    ).json()
    rows = {p["name"]: p for p in body["providers"]}

    assert rows["ollama"]["models"]["main"] == "qwen3:8b"


def test_credentials_are_never_written_to_the_audit_log(client) -> None:
    client.put("/providers/settings", json={"values": {"OPENAI_API_KEY": "sk-secret"}})
    audit = client.get("/audit").text

    assert "sk-secret" not in audit
    assert "OPENAI_API_KEY" in audit  # that it changed is worth recording


# -- OAuth ------------------------------------------------------------------


def test_oauth_state_is_reported_only_for_oauth_providers(client) -> None:
    rows = {p["name"]: p for p in client.get("/providers").json()["providers"]}

    assert rows["codex"]["oauth"]["connected"] is False
    assert rows["codex"]["oauth"]["client_id_env"] == "MARVI_CODEX_CLIENT_ID"
    assert rows["openai"]["oauth"] is None


def test_connecting_a_plan_without_its_client_id_explains_itself(client) -> None:
    response = client.post("/providers/codex/oauth/start")

    assert response.status_code == 400
    assert "MARVI_CODEX_CLIENT_ID" in response.json()["detail"]


def test_starting_a_flow_returns_a_url_to_open_and_never_a_secret(client, monkeypatch) -> None:
    monkeypatch.setenv("MARVI_CODEX_CLIENT_ID", "client-abc")
    body = client.post("/providers/codex/oauth/start").json()

    try:
        assert body["url"].startswith("https://auth.openai.com/oauth/authorize?")
        # Marvi hands over a URL; the user signs in on OpenAI's own page.
        assert "code_challenge=" in body["url"]
        assert "code_verifier" not in body["url"]
    finally:
        client.post("/providers/codex/disconnect")


def test_disconnect_clears_a_key_provider_too(client) -> None:
    client.put("/providers/settings", json={"values": {"OPENAI_API_KEY": "sk-x"}})
    body = client.post("/providers/openai/disconnect").json()
    rows = {p["name"]: p for p in body["providers"]}

    assert rows["openai"]["configured"] is False


# -- the voice path ---------------------------------------------------------


def test_the_agent_is_told_which_provider_to_use(client, monkeypatch) -> None:
    # No local server is running under test, so a key provider is the answer.
    client.put("/providers/settings", json={"values": {"OPENAI_API_KEY": "k"}})
    body = client.get("/providers/voice").json()

    assert body["provider"] == "openai"
    assert body["base_url"].endswith("/v1")
    assert body["model"]


def test_the_agent_receives_openrouter_attribution_headers(client) -> None:
    """Voice calls the provider directly, so the Gateway must carry metadata over."""
    client.put(
        "/providers/settings",
        json={
            "values": {
                "OPENROUTER_API_KEY": "k",
                "MARVI_PROVIDER": "openrouter",
            }
        },
    )

    body = client.get("/providers/voice").json()

    assert body["headers"] == {
        "HTTP-Referer": "https://marvi-alpha.vercel.app/",
        "X-OpenRouter-Title": "Marvi",
    }


def test_a_configured_but_dead_local_server_is_not_offered(client) -> None:
    # Ollama and LM Studio are "configured" the moment they have a default URL.
    # Handing the voice path one that nothing is listening on would break the
    # session at the first turn instead of at startup.
    client.put("/providers/settings", json={"values": {"OPENAI_API_KEY": "k"}})
    assert client.get("/providers/voice").json()["provider"] == "openai"


def test_the_voice_path_only_gets_a_chat_completions_provider(client) -> None:
    # Anthropic's Messages API cannot drive the LiveKit OpenAI plugin, so it
    # must never be handed over as if it could.
    client.put(
        "/providers/settings",
        json={"values": {"ANTHROPIC_API_KEY": "k", "MARVI_PROVIDER": "anthropic"}},
    )
    assert client.get("/providers/voice").status_code == 503

    # And it stays 503 while Anthropic is the selection: a provider chosen in
    # the Models page is locked in, so voice fails loudly rather than quietly
    # answering from something the user never picked.
    client.put("/providers/settings", json={"values": {"OPENAI_API_KEY": "k"}})
    refused = client.get("/providers/voice")
    assert refused.status_code == 503
    assert "cannot drive" in refused.json()["detail"]

    # Choosing one that can drive voice resolves it.
    client.put("/providers/settings", json={"values": {"MARVI_PROVIDER": "openai"}})
    assert client.get("/providers/voice").json()["provider"] != "anthropic"


# -- identity ---------------------------------------------------------------


def test_identity_is_readable_and_writable_from_the_gui(client) -> None:
    # First run seeds the shipped soul, so it is present rather than empty.
    assert "You are Marvi" in client.get("/identity").json()["soul"]

    body = client.put(
        "/identity", json={"soul": "You are terse.", "user": "Shereef. Works late."}
    ).json()

    # And the user's edit replaces it: the soul is theirs.
    assert body["soul"] == "You are terse."
    assert body["tokens"] > 0
    assert body["truncated"] is False


def test_the_budget_is_reported_so_it_can_be_seen_before_it_bites(client) -> None:
    body = client.put("/identity", json={"soul": "x" * 40_000}).json()

    # Every token here is paid on every turn, so the page must show the ceiling.
    assert body["truncated"] is True
    assert body["tokens"] <= body["budget"]


def test_the_voice_role_cannot_hand_the_agent_a_provider_it_cannot_call(
    client, monkeypatch
) -> None:
    """The Agent speaks chat completions and holds the credential itself.

    A role naming a provider the voice path already rejected would hand the
    worker something it cannot call, and that lands as a dead voice session
    rather than as a settings mistake. It falls back to a usable provider and
    logs which role was ignored.
    """
    client.put(
        "/providers/settings",
        json={"values": {"OPENAI_API_KEY": "k", "MARVI_PROVIDER": "openai"}},
    )
    monkeypatch.setenv("MARVI_AUX_VOICE", "anthropic/claude-opus-5")

    answer = client.get("/providers/voice")

    assert answer.status_code == 200
    # Anthropic's Messages API cannot drive the LiveKit plugin, so the role is
    # ignored rather than honoured into a broken session.
    assert answer.json()["provider"] == "openai"


def test_the_voice_role_is_honoured_when_the_path_can_drive_it(client, monkeypatch) -> None:
    client.put(
        "/providers/settings",
        json={"values": {"OPENAI_API_KEY": "k", "MARVI_PROVIDER": "openai"}},
    )
    monkeypatch.setenv("MARVI_AUX_VOICE", "openai/gpt-5-mini")

    answer = client.get("/providers/voice")

    assert answer.status_code == 200
    assert answer.json()["model"] == "gpt-5-mini"
