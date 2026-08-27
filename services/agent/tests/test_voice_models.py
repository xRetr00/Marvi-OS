
def test_a_clause_is_spoken_before_the_sentence_is_finished() -> None:
    """The difference between answering and pausing to compose.

    LiveKit's StreamAdapter batches into sentences of at least twelve
    characters, so a short reply waited for words that were never coming and
    every reply paid that delay before its first sound. The engine takes a
    whole utterance rather than tokens, so some batching is unavoidable —
    owning it is what lets the first clause be spoken as soon as it is one.
    """
    from marvi_agent.voice_models import _next_clause

    clause, rest = _next_clause("The light is on. Anything else?")

    assert clause == "The light is on."
    assert rest == " Anything else?"


def test_an_unfinished_clause_waits() -> None:
    """Speaking half a phrase is worse than a moment's wait."""
    from marvi_agent.voice_models import _next_clause

    assert _next_clause("The light is") == ("", "The light is")


def test_a_fragment_too_short_to_speak_alone_is_held() -> None:
    """"Yes" then "it is" as two utterances sounds like two answers."""
    from marvi_agent.voice_models import _next_clause

    assert _next_clause("Hi.")[0] == ""
def test_the_session_does_not_wrap_the_tts() -> None:
    """A native streaming TTS through StreamAdapter is batching twice."""
    import inspect

    from marvi_agent import session

    # The construction, not the word: the comment above it explains why the
    # adapter is gone and would match a naive search.
    assert "StreamAdapter(" not in inspect.getsource(session.build_session)


def test_a_tool_call_written_as_text_is_not_spoken() -> None:
    """The model wrote the call instead of making it, and Marvi read it aloud.

    From a real session: thirty-nine seconds of audio for one reply, most of it
    tag names and file contents. The tool had not run either -- that is a
    separate fault -- but nothing should ever put markup through the voice.
    """
    from marvi_agent.voice_models import _speakable

    said, markup = _speakable(
        'The file is saved at shreef.txt. <invoke name="file_read">'
    )

    assert said == "The file is saved at shreef.txt."
    assert markup is True


def test_ordinary_speech_passes_through_untouched() -> None:
    from marvi_agent.voice_models import _speakable

    assert _speakable("The light is on.") == ("The light is on.", False)
    # A comparison is not a tag.
    assert _speakable("Three is < five.") == ("Three is < five.", False)
