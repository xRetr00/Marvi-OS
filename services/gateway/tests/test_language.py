"""Which language Marvi listens in, and which she answers in.

The rule was in the prompt -- *always answer in English* -- and it did not
hold. The reason is the thing under test here: the recogniser decides the
language of the transcript, so the model can be looking at a user message
written in another language while one line of instruction asks for English.
The prompt is the weaker half of that argument and it loses.

So the tests that matter are about what each setting can actually enforce.
A setting that cannot enforce itself is worse than no setting: it is a promise.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from marvi_gateway import language
from marvi_gateway.app import create_app


@pytest.fixture(autouse=True)
def clean(monkeypatch):
    monkeypatch.delenv(language.UNDERSTAND_SETTING, raising=False)
    monkeypatch.delenv(language.SPEAK_SETTING, raising=False)


# -- what is set -------------------------------------------------------------


def test_unset_understands_anything(clean) -> None:
    """The default is what Marvi did before this existed."""
    assert language.understand() == language.ANY


def test_unset_speaks_english(clean) -> None:
    assert language.speak() == "en"


def test_an_unknown_code_reads_as_the_default(monkeypatch) -> None:
    """A typo in a settings field must not be what silently changes behaviour."""
    monkeypatch.setenv(language.UNDERSTAND_SETTING, "klingon")
    monkeypatch.setenv(language.SPEAK_SETTING, "klingon")

    assert language.understand() == language.ANY
    assert language.speak() == "en"


def test_a_language_with_no_voice_is_not_speakable(monkeypatch) -> None:
    """Kokoro reads it with English phonemes, which is noise rather than an
    accent, so the setting refuses to hold a language nothing can say."""
    monkeypatch.setenv(language.SPEAK_SETTING, "ru")

    assert language.speak() == "en"


# -- what can be enforced ----------------------------------------------------


def test_english_is_a_lock(monkeypatch) -> None:
    """There is an English-only model to select, so this one is real."""
    monkeypatch.setenv(language.UNDERSTAND_SETTING, "en")

    assert language.enforceable() is True


def test_another_language_is_only_a_preference(monkeypatch) -> None:
    """Parakeet v3 takes no language argument -- NVIDIA's card says it detects
    the language itself, and the request for a parameter was closed without
    one. Saying so is the difference between a setting and a promise."""
    monkeypatch.setenv(language.UNDERSTAND_SETTING, "de")

    assert language.understand() == "de"
    assert language.enforceable() is False


# -- the sentence the model is given -----------------------------------------


def test_the_reply_rule_names_the_chosen_language(monkeypatch) -> None:
    monkeypatch.setenv(language.SPEAK_SETTING, "en")

    assert "in English" in language.reply_instruction()


def test_the_reply_rule_says_why_rather_than_only_what() -> None:
    """A model can act on "the voice pronounces nothing else" when a tool
    result comes back in another language. It cannot act on "do not"."""
    assert "noise" in language.reply_instruction()


# -- voices carry their own language -----------------------------------------


@pytest.mark.parametrize(
    ("voice", "expected"),
    [("am_michael", "en"), ("bf_emma", "en"), ("ef_dora", "es"), ("jf_alpha", "ja")],
)
def test_a_voice_says_its_own_language(voice, expected) -> None:
    """Kokoro's first letter is its language. Its convention, not a table
    invented here, so it cannot fall out of step with the model."""
    assert language.language_of(voice) == expected


def test_the_phoneme_rules_follow_the_voice() -> None:
    """Hardcoded to American English, it read Spanish text with English rules."""
    assert language.g2p_code("es") == "e"
    assert language.g2p_code("en") == "a"


# -- through the Gateway -----------------------------------------------------


def test_the_page_reports_both_settings_and_what_they_enforce() -> None:
    with TestClient(create_app()) as client:
        page = client.get("/language").json()

    assert page["understand"] == language.ANY
    assert page["speak"] == "en"
    assert page["enforceable"] is True
    assert any(option["code"] == "en" for option in page["understand_options"])
    # Only what there is a voice for.
    assert [option["code"] for option in page["speak_options"]] == ["en"]


def test_a_language_nothing_can_say_is_refused_rather_than_ignored() -> None:
    with TestClient(create_app()) as client:
        response = client.put("/language", json={"speak": "ru"})

    assert response.status_code == 400
    assert "voice" in response.text


def test_an_unknown_language_is_refused() -> None:
    with TestClient(create_app()) as client:
        assert client.put("/language", json={"understand": "klingon"}).status_code == 400


def test_the_agent_is_told_the_sentence_rather_than_the_code() -> None:
    """The same rule written out in two packages is two rules that drift --
    which is how voice and chat ended up with different tool lists."""
    with TestClient(create_app()) as client:
        speech = client.get("/voice/speech").json()

    assert speech["stt_language"] == language.ANY
    assert "in English" in speech["reply_instruction"]


def test_the_agent_is_told_the_saved_recogniser_and_chunk(monkeypatch) -> None:
    """The worker cannot inherit settings saved after its process started."""
    monkeypatch.setenv("MARVI_STT_ENGINE", "kyutai-1b")
    monkeypatch.setenv("MARVI_STT_CHUNK", "1.25")

    with TestClient(create_app()) as client:
        speech = client.get("/voice/speech").json()

    assert speech["engine"] == "kyutai-1b"
    assert speech["chunk"] == "1.25"
