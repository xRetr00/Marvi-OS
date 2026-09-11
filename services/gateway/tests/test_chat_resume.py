"""A sub-agent's report, brought back into the Chat conversation that asked.

Voice had `delegated.py`; Chat had nothing. Marvi said "Jarvi's on it", the job
finished, the card turned to FINISHED -- and she never said a word about it,
because a chat turn only happens when the owner sends one. These pin the
continuation: the report goes to the model as a background note (never as the
owner's words), her reply streams like any turn, and one job is reported once.
"""

from __future__ import annotations

import httpx
import pytest

from marvi_gateway.chat import Chat, ChatStore
from marvi_gateway.providers import ProviderClient


def sse(*lines: str) -> str:
    return "".join(f"data: {line}\n" for line in [*lines, "[DONE]"])


REPLY = sse('{"choices":[{"delta":{"content":"Jarvi closed Notepad; the title was Untitled."}}]}')


@pytest.fixture(autouse=True)
def a_provider_to_stream_from(configured):
    configured()


def chat(tmp_path, jobs: dict, seen: list | None = None) -> Chat:
    def handler(request: httpx.Request) -> httpx.Response:
        if seen is not None:
            seen.append(request.read().decode())
        return httpx.Response(200, text=REPLY, headers={"content-type": "text/event-stream"})

    made = Chat(
        store=ChatStore(tmp_path / "chat.sqlite3"),
        client=ProviderClient(http=httpx.Client(transport=httpx.MockTransport(handler))),
    )
    made.job_status = lambda job: jobs.get(job, {"ok": False, "detail": "no job"})
    return made


FINISHED = {
    "ok": True, "id": "j1", "agent": "jarvi", "name": "Jarvi", "state": "completed",
    "exit_reason": "completed", "summary": "Opened Notepad, title Untitled, closed it.",
}


def test_a_finished_job_is_reported_by_marvi_without_being_asked(tmp_path) -> None:
    seen: list[str] = []
    talk = chat(tmp_path, {"j1": FINISHED}, seen)

    events = list(talk.send_stream("", resume_job="j1"))

    assert events[-1]["done"] and not events[-1]["error"]
    assert events[-1]["reply"] == "Jarvi closed Notepad; the title was Untitled."
    # The model was handed the report, marked as not the owner's words.
    assert "Opened Notepad, title Untitled" in seen[0]
    assert "not from the owner" in seen[0]
    history = talk.store.history()
    note, reply = history[-2], history[-1]
    assert note["meta"]["background"] == "job_report" and note["meta"]["job"] == "j1"
    assert reply["role"] == "assistant" and "closed Notepad" in reply["content"]


def test_one_job_is_reported_once(tmp_path) -> None:
    talk = chat(tmp_path, {"j1": FINISHED})
    list(talk.send_stream("", resume_job="j1"))

    again = list(talk.send_stream("", resume_job="j1"))

    assert again[-1]["done"] and again[-1].get("already") is True
    assert sum(1 for row in talk.store.history() if row["meta"].get("job") == "j1") == 1


def test_a_job_still_working_is_not_reported(tmp_path) -> None:
    talk = chat(tmp_path, {"j1": {**FINISHED, "state": "running"}})

    events = list(talk.send_stream("", resume_job="j1"))

    assert "still working" in events[-1]["error"]
    assert talk.store.history() == []


def test_an_unknown_job_is_refused(tmp_path) -> None:
    events = list(chat(tmp_path, {}).send_stream("", resume_job="nope"))
    assert events[-1]["error"]


def test_a_failed_job_is_reported_as_failed(tmp_path) -> None:
    seen: list[str] = []
    failed = {**FINISHED, "state": "failed", "exit_reason": "stalled", "summary": "no progress"}
    list(chat(tmp_path, {"j1": failed}, seen).send_stream("", resume_job="j1"))

    assert "stalled" in seen[0] and "no progress" in seen[0]
