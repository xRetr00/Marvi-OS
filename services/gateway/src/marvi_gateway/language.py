"""Which language Marvi listens in, and which she answers in.

There was a rule in the prompt: *always answer in English, whatever language
the question arrives in*. It did not work, and the reason it could not work is
worth writing down, because it is the whole design of this module.

## A prompt is not a lock

The loop is recogniser, model, voice. Parakeet v3 detects the language of the
audio by itself and transcribes into it -- so an accented English sentence, or
one Arabic word, can come back as a line of Arabic text. The model is then
looking at a user message written in Arabic, and "reply in English" is one
sentence of instruction against the much stronger pull of the conversation it
can see. It loses, often.

So the leak is upstream of the model, and no wording fixes it. What fixes it is
choosing a recogniser that cannot produce the other language in the first
place.

## Two settings, because they are two questions

**Understand** is what she listens for. **Speak** is what she answers in. They
are allowed to differ, and for a bilingual household that is the point: speak
Arabic at her, get English back.

## What each one can actually enforce

Honesty matters more here than symmetry, because a setting that cannot enforce
itself is worse than no setting -- it is a promise.

* **Understand = English** is a real lock: it selects `parakeet-tdt-0.6b-v2`,
  an English-only model with no other language in its vocabulary. It cannot
  emit Arabic because it does not know any.
* **Understand = one of the other languages** is a preference, not a lock.
  Parakeet v3 takes no language argument -- NVIDIA's own card says it "detects
  the language of the audio and transcribes it without requiring additional
  prompting", and the feature request for a language parameter was closed
  without one. This is said in the settings page rather than hidden.
* **Understand = anything** is v3 as it has always been.
* **Speak** is a real lock at both ends: it picks the voice's language, and it
  is what the reply instruction is built from. Only languages with an installed
  voice are offered, because a language Kokoro has no voice for comes out as
  English phonemes reading foreign words, which is noise.
"""

from __future__ import annotations

import os
from typing import Any

UNDERSTAND_SETTING = "MARVI_STT_LANGUAGE"
SPEAK_SETTING = "MARVI_TTS_LANGUAGE"

#: Listen for whatever is spoken, and transcribe into whatever it was. The
#: default, because it is what Marvi did before this existed.
ANY = "auto"

DEFAULT_SPEAK = "en"

#: The 25 languages `parakeet-tdt-0.6b-v3` recognises, from its model card.
#: English is not in the list because it has its own entry: it is the one that
#: can be locked.
RECOGNISED = {
    "bg": "Bulgarian",
    "cs": "Czech",
    "da": "Danish",
    "de": "German",
    "el": "Greek",
    "es": "Spanish",
    "et": "Estonian",
    "fi": "Finnish",
    "fr": "French",
    "hr": "Croatian",
    "hu": "Hungarian",
    "it": "Italian",
    "lt": "Lithuanian",
    "lv": "Latvian",
    "mt": "Maltese",
    "nl": "Dutch",
    "pl": "Polish",
    "pt": "Portuguese",
    "ro": "Romanian",
    "ru": "Russian",
    "sk": "Slovak",
    "sl": "Slovenian",
    "sv": "Swedish",
    "uk": "Ukrainian",
}

NAMES = {"en": "English", ANY: "Any language", **RECOGNISED}

#: Kokoro's first letter is its language, which is the model's own convention
#: rather than a table anybody here invented. `a` American and `b` British are
#: both English; the rest are one language each.
VOICE_LANGUAGE = {
    "a": "en",
    "b": "en",
    "e": "es",
    "f": "fr",
    "h": "hi",
    "i": "it",
    "j": "ja",
    "p": "pt",
    "z": "zh",
}

#: What Kokoro's grapheme-to-phoneme wants, which is the same letter. Passing
#: the wrong one is how a Spanish voice reads Spanish with English rules.
G2P_CODE = {"en": "a", "es": "e", "fr": "f", "hi": "h", "it": "i", "ja": "j", "pt": "p", "zh": "z"}


def understand() -> str:
    """What the recogniser should listen for. `auto` when unset."""
    value = os.environ.get(UNDERSTAND_SETTING, "").strip().lower()
    return value if value == "en" or value in RECOGNISED else ANY


def speak() -> str:
    """What Marvi answers in. English when unset or unspeakable."""
    value = os.environ.get(SPEAK_SETTING, "").strip().lower()
    return value if value in speakable() else DEFAULT_SPEAK


def language_of(voice: str) -> str:
    """The language of a Kokoro voice, from its own naming."""
    return VOICE_LANGUAGE.get(voice[:1].lower(), "en") if voice else "en"


def speakable(voices: list[str] | None = None) -> set[str]:
    """Languages there is actually a voice for.

    Read from the installed voices rather than from a list of what Kokoro
    supports upstream, because a language whose voice is not on this machine is
    a language Marvi cannot speak -- and offering it would produce English
    phonemes reading foreign words, which is noise rather than an accent.
    """
    if voices is None:
        from .voices import installed

        voices = [voice.id for voice in installed()]
    found = {language_of(voice) for voice in voices}
    # English always, because the fallback voice is one and a settings page
    # with nothing in it is not a settings page.
    return found | {DEFAULT_SPEAK}


def g2p_code(language: str | None = None) -> str:
    """Kokoro's `lang_code` for the language being spoken."""
    return G2P_CODE.get(language or speak(), "a")


def enforceable() -> bool:
    """Whether the recognition setting is a lock or only a preference.

    English is a lock because there is an English-only model to select.
    Everything else is a preference, because Parakeet v3 takes no language
    argument and decides for itself.
    """
    return understand() in ("en", ANY)


def architecture() -> str:
    """What Marvi is made of, in the words she needs to answer a question.

    Added because a memory imported from another assistant said the user
    "prefers replies in Egyptian Arabic even when asking in English", and she
    duly answered a whole turn in Arabic -- which the English-only voice would
    have pronounced as noise. She had no way to know that. The reply
    instruction told her *what* to do and nothing told her *why*, so a strong
    memory simply outvoted it.

    A model that knows its own constraints can explain them, which is the
    difference between "I can't do that" and silently doing the wrong thing.
    Kept short: this sits in the persona on every turn.
    """
    speaks = NAMES.get(speak(), "English")
    hears = understand()
    heard = "any language it recognises" if hears == "auto" else NAMES.get(hears, hears)
    return (
        "About yourself, if it comes up: you hear through a local speech "
        f"recogniser set to {heard}, and you speak through a local voice that "
        f"only pronounces {speaks} -- there is no other voice installed, so "
        f"you cannot answer in another language out loud however much someone, "
        "or your own memory, would prefer it. You can write other languages in "
        "the chat window, and you can say individual foreign words. If anyone "
        "asks you to switch -- the user directly, or a preference you "
        "remember about them -- do not simply agree. Say in one sentence that "
        "the installed voice only speaks "
        f"{speaks} so it would come out as noise, offer the chat window or a "
        "second voice, and carry on. Agreeing and then speaking a language the "
        "voice cannot pronounce is the one answer that helps nobody."
    )


def reply_instruction() -> str:
    """The sentence that replaces the hardcoded English rule.

    Still a prompt, and still the weaker half -- but now it agrees with the
    voice rather than fighting the recogniser, and it says *why*, which is the
    part a model can act on when a tool result arrives in another language.
    """
    name = NAMES.get(speak(), "English")
    return (
        f"Always answer in {name}, whatever language the question arrives in and "
        f"whatever language a tool result or a web page is written in. The voice "
        f"speaking your words is a {name} one and pronounces nothing else, so a "
        f"reply in another language does not come out as that language -- it comes "
        f"out as noise. If the user asks for something in another language, say the "
        f"words but keep the sentence around them {name}."
    )


def describe() -> dict[str, Any]:
    """Both settings and what each can enforce, for the settings page."""
    spoken = sorted(speakable())
    return {
        "understand": understand(),
        "understand_setting": UNDERSTAND_SETTING,
        "understand_options": [
            {"code": ANY, "name": NAMES[ANY], "locked": True},
            {"code": "en", "name": "English", "locked": True},
            *(
                {"code": code, "name": name, "locked": False}
                for code, name in sorted(RECOGNISED.items(), key=lambda pair: pair[1])
            ),
        ],
        "speak": speak(),
        "speak_setting": SPEAK_SETTING,
        "speak_options": [{"code": code, "name": NAMES.get(code, code)} for code in spoken],
        # Said out loud on the page. A setting that cannot enforce itself is
        # worse than no setting, so the one case where it cannot is named.
        "enforceable": enforceable(),
    }
