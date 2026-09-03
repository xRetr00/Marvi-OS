"""The logging engine.

Two properties are load-bearing, and both are tested by reading the files that
were actually written rather than by trusting a call site: **nothing is lost**,
and **nothing leaks**.

Every test configures a fresh engine into `tmp_path` and tears it down, because
logging is process-global state and a leaked handler poisons the next test.
"""

from __future__ import annotations

import logging
import threading
import warnings

import pytest

from marvi_gateway import logs


@pytest.fixture
def engine(tmp_path, monkeypatch):
    monkeypatch.setenv("MARVI_LOG_DIR", str(tmp_path))
    monkeypatch.setenv("MARVI_LOG_LEVEL", "DEBUG")
    logs.shutdown()
    logs.configure(tmp_path, level="DEBUG", console=False)
    logs.redactor().refresh()
    yield tmp_path
    logs.shutdown()


def read(directory, name: str) -> str:
    path = directory / f"{name}.log"
    return path.read_text(encoding="utf-8") if path.exists() else ""


def settle() -> None:
    """Wait for the queue listener to drain, since writes are off-thread."""
    listener = logs._listener
    if listener is not None and listener.queue is not None:
        for _ in range(200):
            if listener.queue.empty():
                break
            threading.Event().wait(0.01)
    threading.Event().wait(0.15)


# -- routing -----------------------------------------------------------------


def test_each_subsystem_gets_its_own_file(engine) -> None:
    logging.getLogger("marvi_gateway.providers.client").info("called a model")
    logging.getLogger("marvi_gateway.room").info("light on")
    settle()

    # A merged log is unreadable within a day; the split is the point.
    assert "called a model" in read(engine, "providers")
    assert "light on" in read(engine, "room")
    assert "light on" not in read(engine, "providers")


def test_the_longest_prefix_wins(engine) -> None:
    # marvi_gateway.providers.oauth must not fall back to the gateway file just
    # because marvi_gateway is also a known prefix.
    assert logs.subsystem_for("marvi_gateway.providers.oauth") == "providers"
    assert logs.subsystem_for("marvi_gateway.chat") == "chat"


def test_library_loggers_are_claimed(engine) -> None:
    # A connection error from httpx is usually the most useful line in the file.
    logging.getLogger("httpx").warning("connection refused")
    logging.getLogger("uvicorn.error").info("listening")
    settle()

    assert "connection refused" in read(engine, "providers")
    assert "listening" in read(engine, "gateway")


def test_an_unmapped_module_is_not_dropped(engine) -> None:
    logging.getLogger("some.random.library").info("still recorded")
    settle()

    assert "still recorded" in read(engine, "gateway")


def test_adding_a_subsystem_is_one_call(engine) -> None:
    logs.get_logger("weather").info("it is raining")
    settle()

    # No registry to edit, no handler to wire.
    assert "it is raining" in read(engine, "weather")


# -- the error fan-in --------------------------------------------------------


def test_warnings_and_errors_collect_in_one_place(engine) -> None:
    logging.getLogger("marvi_gateway.room").warning("sidecar slow")
    logging.getLogger("marvi_gateway.providers.client").error("provider down")
    logging.getLogger("marvi_gateway.room").info("routine poll")
    settle()

    errors = read(engine, "errors")
    # errors.log answers "what went wrong", which is the question people have.
    assert "sidecar slow" in errors
    assert "provider down" in errors
    assert "routine poll" not in errors


def test_errors_stay_in_their_own_subsystem_file_too(engine) -> None:
    logging.getLogger("marvi_gateway.room").error("sidecar died")
    settle()

    assert "sidecar died" in read(engine, "room")
    assert "sidecar died" in read(engine, "errors")


# -- nothing leaks -----------------------------------------------------------


def test_a_known_secret_never_reaches_disk(engine, monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_API_KEY", "sk-supersecretvalue123456")
    logs.redactor().refresh()

    logging.getLogger("marvi_gateway.providers.client").info(
        "calling with key sk-supersecretvalue123456"
    )
    settle()

    for name in logs.available(engine):
        assert "sk-supersecretvalue123456" not in read(engine, name), name
    assert "[redacted]" in read(engine, "providers")


def test_a_secret_passed_as_an_argument_is_scrubbed(engine, monkeypatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "kk-lazyformatting-999")
    logs.redactor().refresh()

    # Lazy %-formatting means the secret is in args, not in msg.
    logging.getLogger("marvi_gateway.providers.client").info(
        "auth=%s", "kk-lazyformatting-999"
    )
    settle()

    assert "kk-lazyformatting-999" not in read(engine, "providers")


def test_a_secret_inside_a_url_is_scrubbed(engine, monkeypatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "abcdefgh12345678")
    logs.redactor().refresh()

    # A field-name filter would never look here. Value-based redaction does.
    logging.getLogger("httpx").info(
        "GET https://api.example.com/v1/models?api_key=abcdefgh12345678"
    )
    settle()

    assert "abcdefgh12345678" not in read(engine, "providers")


def test_a_secret_in_a_traceback_is_scrubbed(engine, monkeypatch) -> None:
    monkeypatch.setenv("OPENCODE_GO_API_KEY", "tok-in-a-traceback-1234")
    logs.redactor().refresh()

    try:
        raise RuntimeError("failed with tok-in-a-traceback-1234")
    except RuntimeError:
        logging.getLogger("marvi_gateway.providers.client").exception("call failed")
    settle()

    assert "tok-in-a-traceback-1234" not in read(engine, "providers")
    assert "tok-in-a-traceback-1234" not in read(engine, "errors")


def test_an_oauth_token_can_be_registered_at_runtime(engine) -> None:
    # Access tokens arrive over HTTP and are stored encrypted, so they are never
    # environment variables and nothing else would know to hide them.
    logs.redactor().add("oauth-access-token-value")
    logging.getLogger("marvi_gateway.providers.oauth").info(
        "refreshed to oauth-access-token-value"
    )
    settle()

    assert "oauth-access-token-value" not in read(engine, "providers")


def test_unknown_token_shapes_are_caught_by_pattern(engine) -> None:
    # A second layer for credentials Marvi was never handed.
    logging.getLogger("httpx").info(
        "headers: {'authorization': 'Bearer eyJhbGciOiJIUzI1NiJ9.payload.sig'}"
    )
    settle()

    assert "eyJhbGciOiJIUzI1NiJ9.payload.sig" not in read(engine, "providers")


def test_short_values_are_not_treated_as_secrets(engine, monkeypatch) -> None:
    monkeypatch.setenv("MARVI_TOKEN_STORE", "abc")
    logs.redactor().refresh()

    # Scrubbing a three-character value would blank out ordinary words.
    logging.getLogger("marvi_gateway.room").info("the abc of it")
    settle()

    assert "the abc of it" in read(engine, "room")


# -- nothing is lost ---------------------------------------------------------


def test_an_uncaught_exception_on_a_thread_is_recorded(engine) -> None:
    def explode() -> None:
        raise ValueError("thread died alone")

    worker = threading.Thread(target=explode, name="doomed")
    worker.start()
    worker.join()
    settle()

    # sys.excepthook covers the main thread only; this is the failure that
    # otherwise happens in total silence.
    errors = read(engine, "errors")
    assert "thread died alone" in errors
    assert "doomed" in errors


def test_an_uncaught_exception_on_the_main_thread_is_recorded(engine) -> None:
    try:
        raise KeyError("main thread crash")
    except KeyError:
        import sys

        sys.excepthook(*sys.exc_info())
    settle()

    assert "main thread crash" in read(engine, "errors")


def test_a_keyboard_interrupt_is_not_swallowed(engine) -> None:
    import sys

    # Ctrl-C is a user action, not a crash; it must reach the default handler.
    original = sys.__excepthook__
    seen: list[str] = []
    sys.__excepthook__ = lambda kind, value, tb: seen.append(kind.__name__)  # type: ignore[assignment]
    try:
        sys.excepthook(KeyboardInterrupt, KeyboardInterrupt(), None)
    finally:
        sys.__excepthook__ = original  # type: ignore[assignment]

    assert seen == ["KeyboardInterrupt"]


def test_warnings_are_captured(engine) -> None:
    warnings.warn("this predicts the next breakage", DeprecationWarning, stacklevel=1)
    settle()

    assert "this predicts the next breakage" in read(engine, "errors")


@pytest.mark.asyncio
async def test_asyncio_errors_are_captured(engine) -> None:
    import asyncio

    loop = asyncio.get_running_loop()
    logs.install_asyncio_handler(loop)
    loop.call_exception_handler({"message": "task exception never retrieved"})
    settle()

    assert "task exception never retrieved" in read(engine, "errors")


def test_output_from_another_process_joins_the_timeline(engine) -> None:
    # The Electron shell and the supervised services write their own stdout.
    logs.ingest("desktop", "gateway exited with code 3", level=logging.ERROR)
    settle()

    assert "gateway exited with code 3" in read(engine, "desktop")
    assert "gateway exited with code 3" in read(engine, "errors")


# -- operational -------------------------------------------------------------


def test_configure_is_idempotent(engine) -> None:
    # Every entry point calls it; the second call must not duplicate handlers.
    logs.configure(engine, console=False)
    logging.getLogger("marvi_gateway.room").info("only once")
    settle()

    assert read(engine, "room").count("only once") == 1


def test_a_logging_failure_never_becomes_an_application_failure(engine) -> None:
    class Hostile:
        def __str__(self) -> str:
            raise RuntimeError("repr exploded")

    # Tested against the filter directly rather than through a logger call:
    # pytest attaches its own capture handler to the root logger, and that one
    # formats synchronously in the caller. Marvi's own path is the filter, and
    # this is the guarantee it has to make.
    record = logging.LogRecord(
        "marvi_gateway.room", logging.INFO, __file__, 1, "value: %s", (Hostile(),), None
    )
    assert logs.RedactionFilter().filter(record) is True
    assert "value:" in str(record.msg)


def test_tail_reads_the_end_of_a_file(engine) -> None:
    for n in range(500):
        logging.getLogger("marvi_gateway.room").info("line %d", n)
    settle()

    last = logs.tail("room", lines=5, directory=engine)
    assert len(last) == 5
    assert "line 499" in last[-1]


def test_tail_of_a_missing_file_is_empty_not_an_error(engine) -> None:
    assert logs.tail("nothing-here", directory=engine) == []


def test_available_lists_what_exists(engine) -> None:
    logging.getLogger("marvi_gateway.room").info("hello")
    settle()

    assert "room" in logs.available(engine)


def test_extras_are_rendered_for_machines_and_people(engine) -> None:
    logging.getLogger("marvi_gateway.providers.client").info(
        "call complete", extra={"marvi_provider": "ollama", "marvi_tokens": 42}
    )
    settle()

    line = read(engine, "providers")
    # The same line has to serve a person reading it and a script parsing it.
    assert "call complete" in line
    assert "marvi_provider='ollama'" in line
    assert "marvi_tokens=42" in line


def test_a_client_hanging_up_is_not_an_error() -> None:
    """388 of these filled errors.log in one session and made a healthy
    Gateway look like a crashing one.

    On Windows the proactor transport raises ConnectionResetError when a client
    drops a connection, and an HTTP client is allowed to do that.
    """
    from marvi_gateway.logs import is_client_hangup

    hangup = {
        "message": "Exception in callback _ProactorBasePipeTransport._call_connection_lost()",
        "exception": ConnectionResetError(10054, "forcibly closed by the remote host"),
    }
    assert is_client_hangup(hangup) is True


def test_a_reset_that_is_not_a_transport_teardown_stays_an_error() -> None:
    """Recognised specifically. A provider dropping mid-call is a real event."""
    from marvi_gateway.logs import is_client_hangup

    assert is_client_hangup(
        {"message": "provider stream failed", "exception": ConnectionResetError("reset")}
    ) is False
    assert is_client_hangup(
        {"message": "_call_connection_lost", "exception": RuntimeError("something else")}
    ) is False
    assert is_client_hangup({"message": "task exception was never retrieved"}) is False


def test_the_routine_heartbeat_stays_out_of_the_access_log() -> None:
    """959 KB of `gateway.log` for one idle afternoon, and 335 of 335 lines nothing.

    The desktop asks the same handful of endpoints on a timer forever -- is the
    wake word on, is anything running, how much has been spent. Each answer
    wrote an access line, and the one real event in that file, a crash loop,
    had to be dug out from under them.
    """
    import logging

    from marvi_gateway.logs import QuietPollingFilter

    def access(path: str, status: int) -> logging.LogRecord:
        record = logging.LogRecord(
            "uvicorn.access", logging.INFO, __file__, 0, '%s - "%s %s HTTP/%s" %d', None, None
        )
        record.args = ("127.0.0.1:49649", "GET", path, "1.1", status)
        return record

    quiet = QuietPollingFilter()
    assert quiet.filter(access("/voice/wake", 200)) is False
    assert quiet.filter(access("/usage?refresh=false", 200)) is False
    assert quiet.filter(access("/runtime", 200)) is False

    # Anything that is not the heartbeat still shows.
    assert quiet.filter(access("/chat", 200)) is True
    assert quiet.filter(access("/voice/transcript", 200)) is True

    # And a poll that failed is exactly what this log is for.
    assert quiet.filter(access("/voice/wake", 500)) is True
    assert quiet.filter(access("/runtime", 404)) is True


def test_a_record_it_cannot_read_is_kept() -> None:
    # This filter removes noise. Guessing wrong about an unfamiliar record
    # should lose nothing, so anything not shaped like an access line passes.
    import logging

    from marvi_gateway.logs import QuietPollingFilter

    quiet = QuietPollingFilter()
    plain = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 0, "started", None, None)
    assert quiet.filter(plain) is True

    odd = logging.LogRecord("uvicorn.access", logging.INFO, __file__, 0, "%s", None, None)
    odd.args = ("127.0.0.1", "GET", None, "1.1", "who knows")
    assert quiet.filter(odd) is True
