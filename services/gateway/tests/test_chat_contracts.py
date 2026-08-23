from __future__ import annotations

import base64
import io
import json
from pathlib import Path

import pytest

from marvi_gateway import dictation
from marvi_gateway.chat import Chat, ChatStore
from marvi_gateway.providers import get as provider_get
from marvi_gateway.providers.base import Usage
from marvi_gateway.providers.client import Completion


def test_threads_survive_restart_without_mixing_history(tmp_path: Path) -> None:
    path = tmp_path / "chat.sqlite3"
    store = ChatStore(path)
    second = store.create_thread("Room research")
    store.append("user", "default turn")
    store.append("user", "other turn", thread_id=second["id"])
    store.close()

    reopened = ChatStore(path)
    assert [row["content"] for row in reopened.history()] == ["default turn"]
    assert [row["content"] for row in reopened.history(thread_id=second["id"])] == ["other turn"]
    assert {thread["title"] for thread in reopened.threads()} == {
        "default turn",
        "Room research",
    }


def test_model_selection_is_scoped_to_and_persisted_with_thread(tmp_path: Path) -> None:
    path = tmp_path / "chat.sqlite3"
    store = ChatStore(path)
    second = store.create_thread("Different model")
    store.set_thread_model(second["id"], "anthropic", "claude-test", "high")
    store.close()

    reopened = ChatStore(path)
    default = reopened.get_thread("default")
    selected = reopened.get_thread(second["id"])
    assert (default["selected_provider"], default["selected_model"]) == ("", "")
    assert (
        selected["selected_provider"],
        selected["selected_model"],
        selected["selected_effort"],
    ) == ("anthropic", "claude-test", "high")


def test_thread_model_selection_routes_the_turn(tmp_path: Path) -> None:
    class RecordingClient:
        def __init__(self) -> None:
            self.preferred = None

        def candidates(self, _preferred=None):
            return [object()]

        def call_with_fallback(self, _messages, **kwargs):
            self.preferred = kwargs["preferred"]
            return Completion(
                text="routed",
                usage=Usage(),
                provider=str(self.preferred),
                model=str(kwargs["model"]),
            )

    store = ChatStore(tmp_path / "chat.sqlite3")
    thread = store.create_thread("Route")
    store.set_thread_model(thread["id"], "anthropic", "claude-test", "high")
    client = RecordingClient()

    turn = Chat(store=store, client=client).send("hello", thread_id=thread["id"])

    assert turn.reply == "routed"
    assert client.preferred == "anthropic"


def test_edit_and_regenerate_preserve_original_branch(tmp_path: Path) -> None:
    store = ChatStore(tmp_path / "chat.sqlite3")
    original_user = store.append("user", "original")
    original_answer = store.append("assistant", "first answer")

    _, edited_user = store.fork_user(original_user, "edited")
    store.append("assistant", "edited answer")
    assert [row["content"] for row in store.history()] == ["edited", "edited answer"]

    thread_id, user = store.prepare_regenerate(original_answer)
    assert thread_id == "default"
    assert user["content"] == "original"
    store.append("assistant", "second answer")
    assert [row["content"] for row in store.history()] == ["original", "second answer"]
    assert store._db.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 5
    assert edited_user != original_user


def test_attachment_is_typed_bound_and_removed_with_thread(tmp_path: Path) -> None:
    store = ChatStore(tmp_path / "chat.sqlite3")
    attachment = store.add_attachment(
        "default", "notes.md", "text/markdown", b"# Evidence\n\nLocal only."
    )
    message_id = store.append(
        "user",
        "Read this",
        attachment_ids=[attachment["id"]],
        parts=[
            {"type": "text", "text": "Read this"},
            {"type": "attachment", "attachment_id": attachment["id"]},
        ],
    )

    row = store.history()[0]
    assert row["parts"][1]["type"] == "attachment"
    assert row["attachments"][0]["name"] == "notes.md"
    assert "Local only" in str(store.provider_content(message_id, "Read this"))
    stored_path = Path(
        store._db.execute(
            "SELECT path FROM attachments WHERE id = ?", (attachment["id"],)
        ).fetchone()[0]
    )
    assert stored_path.is_file()
    store.clear()
    assert not stored_path.exists()


@pytest.mark.parametrize(
    ("provider", "expected_type"),
    [("openai", "image_url"), ("openai-responses", "input_image"), ("anthropic", "image")],
)
def test_image_parts_translate_to_each_provider_wire_format(
    provider: str, expected_type: str
) -> None:
    profile = provider_get(provider)
    body = profile.build_request(
        [
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "What is this?"},
                    {"type": "image", "media_type": "image/png", "data": "AA=="},
                ],
            }
        ],
        model="test-model",
    )
    messages = body.get("messages") or body.get("input")
    content = messages[0]["content"]
    assert any(part["type"] == expected_type for part in content)


class _FakeStdout:
    def __init__(self) -> None:
        self.lines = [json.dumps({"ok": True, "kind": "ready", "text": "en-US"}) + "\n"]

    def readline(self) -> str:
        return self.lines.pop(0) if self.lines else ""


class _FakeStdin:
    def __init__(self, stdout: _FakeStdout) -> None:
        self.stdout = stdout

    def write(self, value: str) -> None:
        request = json.loads(value)
        kind = "partial" if request["op"] == "audio" else "final"
        text = "hello" if kind == "partial" else " world"
        self.stdout.lines.append(json.dumps({"ok": True, "kind": kind, "text": text}) + "\n")

    def flush(self) -> None:
        return None


class _FakeProcess:
    def __init__(self) -> None:
        self.stdout = _FakeStdout()
        self.stdin = _FakeStdin(self.stdout)
        self.stderr = io.StringIO()
        self.returncode = None

    def poll(self):
        return self.returncode

    def terminate(self) -> None:
        self.returncode = 0

    def wait(self, timeout: int | None = None) -> int:
        del timeout
        return 0

    def kill(self) -> None:
        self.returncode = -1


def test_dictation_streams_pcm_to_existing_sidecar_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model = tmp_path / "model"
    model.mkdir()
    (model / "encoder-model.onnx").write_bytes(b"stub")
    monkeypatch.setattr(dictation, "worker_command", lambda: ["python", "worker.py"])
    monkeypatch.setattr(dictation, "model_path", lambda: model)
    process = _FakeProcess()
    manager = dictation.DictationManager(popen=lambda *_args, **_kwargs: process)

    session_id = manager.start()
    chunk = base64.b64encode(b"\x00\x00\x01\x00").decode()
    assert manager.audio(session_id, chunk)["text"] == "hello"
    assert manager.stop(session_id)["kind"] == "final"
    assert process.returncode == 0
