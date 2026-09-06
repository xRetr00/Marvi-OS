"""What the store refuses to keep, and why it checks instead of asking.

Every string in this file is a real row from the owner's memory database or a
real line from the extraction prompt. The prompt has forbidden this since it
was written -- "Never store the assistant's own words, pleasantries, or the
fact that a conversation happened" -- and 55 of the 199 memories in that
database were exactly that.
"""

from __future__ import annotations

import pytest

from marvi_gateway import remembering


class _Store:
    def __init__(self) -> None:
        self.kept: list[tuple[str, str]] = []

    def remember(self, subject, body, kind="semantic", **_):
        self.kept.append((subject, body))

    def forget(self, _id):
        return True


#: Verbatim from the store. Each was recalled into later turns as though it
#: bore on them, and each was built out of a misheard sentence.
JUNK = [
    ("User's greeting and status",
     "The user said 'Yeah, I was wondering I was going on.' which Marvi "
     "interpreted as a greeting or status update."),
    ("User checking on assistant",
     "The user confirmed they were checking on the assistant's status."),
    ("User's farewell and end of interaction",
     "The user said 'Thank you, no singles. You can end up in.' and the "
     "assistant responded with 'Goodnight, Shereef.'"),
    ("User's sleep mode request",
     "The user asked to activate a sleep mood, and the assistant confirmed it "
     "was already done."),
    ("User asking about something new",
     "The user said 'Yes, I was asking about the new new new' which indicates "
     "they were inquiring about something new."),
]

#: Also verbatim, from the dreaming pass. This is what a memory looks like.
REAL = [
    ("Shereef's home automation setup",
     "Shereef uses Home Assistant for home automation and has a RGBCW "
     "lightbulb (entity_id light.rgbcw_lightbulb) in their room."),
    ("Marvi's capabilities",
     "Marvi can control the room, check the calendar, search the web, read "
     "files, run commands, handle email, and delegate coding tasks."),
    ("Marvi's local architecture",
     "Marvi runs as four local processes: Desktop, Gateway, Agent and Sidecar."),
    ("The user's keyboard", "The user owns a Keychron K2 keyboard."),
    ("The user's schedule", "The user starts work at 4am on Fridays."),
    # A dry run over the real store caught these with a broader pattern. Both
    # are facts *about* the assistant rather than narration of something it
    # said, and losing them is the cost of matching the word "assistant"
    # instead of matching somebody speaking.
    ("Hermes infrastructure",
     "The backend infrastructure of the assistant system is named Hermes, "
     "which has remained constant despite multiple rebrandings."),
    ("Gmail authentication barrier",
     "Gmail requires re-authentication, and the assistant cannot check email "
     "until the user signs in or authorizes API access."),
]


@pytest.mark.parametrize(("subject", "body"), JUNK)
def test_a_memory_about_the_conversation_is_refused(subject, body) -> None:
    store = _Store()
    done = remembering.apply(store, [{"op": "add", "subject": subject, "body": body}])
    assert store.kept == [], f"kept {store.kept}"
    assert done["ignored"] == 1


@pytest.mark.parametrize(("subject", "body"), REAL)
def test_a_memory_about_the_world_is_kept(subject, body) -> None:
    store = _Store()
    remembering.apply(store, [{"op": "add", "subject": subject, "body": body}])
    assert store.kept == [(subject, body)]


def test_a_body_that_is_not_text_is_refused() -> None:
    """Two rows in the real store have a Python dict repr for a body.

        subject: User shared a link
        body:    {'id': 'User shared a link'}

    The model answered with an object where a sentence belongs and
    `str(...)` took it without complaint.
    """
    store = _Store()
    done = remembering.apply(
        store,
        [{"op": "add", "subject": "User shared a link", "body": {"id": "User shared a link"}}],
    )
    assert store.kept == []
    assert done["ignored"] == 1
