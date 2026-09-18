"""Taking notes in a meeting: what was said, what was decided, what is now owed.

Marvi could see the calendar and nothing of the meeting. This records both
sides of one -- the microphone for the owner, the speakers for everyone else --
and turns it into a transcript, a summary, the decisions, and action items that
land on the jobs board as cards.

## Never automatic

Nothing here starts on its own. A meeting with a video link makes Marvi *offer*
("take notes?"); the recording begins when the owner says yes, and the first
time it is ever offered they get a plain notice about what recording other
people means, which they have to accept once. `due()` finds the offer;
`start()` is the only thing that opens a microphone, and it refuses until the
notice has been accepted.

While it runs, `now()` reports it, so the window can show an indicator for the
whole session. That is not a nicety: a machine that can record a room without
saying so is a different product, and the indicator is the difference.

## Recorded live, transcribed afterwards

The obvious design runs two speech recognisers for the length of the call. Two
copies of a 0.6B model on a card that is also carrying the voice session is how
"voice latency unaffected during the call" stops being true, and the acceptance
for this feature asks for exactly that.

So the call costs two WAV writers and nothing else, and the transcription
happens when it ends. Each side is cut into windows, each window is timed and
transcribed on its own, silent windows are skipped, and the windows from both
sides are interleaved by when they happened. That is what gives speaker turns
without diarisation: *which stream it arrived on* is the speaker, and it is
exact rather than inferred.

## What leaves the machine

The transcript does not. Recognition is the local recogniser, the same one
dictation uses. Only the summary step calls a model, and it is the auxiliary
route -- so with a local auxiliary provider, or privacy mode, a meeting is
recorded, transcribed and summarised without anything leaving the machine.
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
import wave
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from uuid import uuid4

from . import audiocapture
from .logs import get_logger

log = get_logger("gateway")

STATES = ("recording", "transcribing", "ready", "failed")

#: How much of one side is transcribed at a time. Long enough that a sentence
#: is rarely cut in half, short enough that a turn is placed to the half minute.
WINDOW_SECONDS = 30

#: Below this peak a window is silence and is not transcribed. One side of a
#: call is quiet most of the time, and transcribing that is most of the cost.
#: 0-32767; 300 is a quiet room, a whisper still clears it.
SILENCE_PEAK = 300

#: A meeting longer than this stops recording itself. A forgotten recording is
#: the failure mode that matters, and six hours of it is worse than a lost end.
MAX_SECONDS = 6 * 60 * 60

#: Shown once, before Marvi ever records anything.
CONSENT = (
    "Recording a meeting records the other people in it. In many places you "
    "need their agreement before you do, and in some it is the law. Marvi will "
    "not check for you and cannot tell where you are.\n\n"
    "What Marvi does: records your microphone and whatever your speakers are "
    "playing, keeps both on this machine, transcribes them here, and shows an "
    "indicator the whole time it is recording. Nothing is uploaded; only the "
    "summary step asks a model, and with a local one even that stays here.\n\n"
    "You start every recording yourself. Marvi can offer, and never begins."
)

SCHEMA = """
CREATE TABLE IF NOT EXISTS meetings (
    id          TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    state       TEXT NOT NULL DEFAULT 'recording',
    detail      TEXT NOT NULL DEFAULT '',
    started_at  TEXT NOT NULL,
    ended_at    TEXT NOT NULL DEFAULT '',
    seconds     INTEGER NOT NULL DEFAULT 0,
    folder      TEXT NOT NULL DEFAULT '',
    summary     TEXT NOT NULL DEFAULT '',
    decisions   TEXT NOT NULL DEFAULT '[]',
    actions     TEXT NOT NULL DEFAULT '[]',
    calendar_id TEXT NOT NULL DEFAULT ''
);
CREATE TABLE IF NOT EXISTS meeting_turns (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    meeting_id TEXT NOT NULL REFERENCES meetings(id) ON DELETE CASCADE,
    at_seconds INTEGER NOT NULL,
    speaker    TEXT NOT NULL,
    text       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS meeting_turns_one ON meeting_turns(meeting_id, at_seconds);
CREATE TABLE IF NOT EXISTS meeting_consent (
    id         INTEGER PRIMARY KEY CHECK (id = 1),
    accepted_at TEXT NOT NULL
);
"""


class MeetingError(RuntimeError):
    """Something a person asked for cannot be done, with a reason for them."""


class ConsentNeededError(MeetingError):
    """The notice has not been accepted, so nothing is recorded."""


def default_path() -> Path:
    from .paths import root

    return root() / "meetings.sqlite3"


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class Meetings:
    """Every meeting taken, and the one being taken now."""

    def __init__(self, path: Path | None = None, folder: Path | None = None) -> None:
        self.path = path or default_path()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.folder = folder or (self.path.parent / "meetings")
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._db.commit()
        self._lock = threading.Lock()
        self._live: _Recording | None = None
        #: Supplied by the Gateway. `(client)` for the summary, `(store)` for
        #: the cards -- kept as attributes so this module does not import the
        #: whole app to write down what somebody said.
        self.client: Any = None
        self.board: Any = None
        #: PCM16 at `audiocapture.TARGET_RATE` in, text out. The Gateway
        #: supplies the same local recogniser a voice note goes through.
        self.transcribe: Callable[[bytes], str] | None = None

    # -- consent --------------------------------------------------------------

    def consent(self) -> dict[str, Any]:
        row = self._db.execute("SELECT accepted_at FROM meeting_consent WHERE id = 1").fetchone()
        return {"notice": CONSENT, "accepted": bool(row), "accepted_at": row["accepted_at"] if row else ""}

    def accept_consent(self) -> dict[str, Any]:
        with self._lock:
            self._db.execute(
                "INSERT OR REPLACE INTO meeting_consent (id, accepted_at) VALUES (1, ?)", (_now(),)
            )
            self._db.commit()
        return self.consent()

    # -- recording ------------------------------------------------------------

    def start(self, title: str = "", calendar_id: str = "") -> dict[str, Any]:
        """Begin recording. The only thing here that opens a microphone."""
        if not self.consent()["accepted"]:
            raise ConsentNeededError("the recording notice has not been accepted yet")
        can, why = audiocapture.available()
        if not can:
            raise MeetingError(why)
        with self._lock:
            if self._live is not None:
                raise MeetingError("a meeting is already being recorded")
            identifier = uuid4().hex[:12]
            where = self.folder / identifier
            where.mkdir(parents=True, exist_ok=True)
            self._db.execute(
                "INSERT INTO meetings (id, title, state, started_at, folder, calendar_id)"
                " VALUES (?, ?, 'recording', ?, ?, ?)",
                (identifier, " ".join((title or "").split())[:160] or "Meeting", _now(),
                 str(where), calendar_id),
            )
            self._db.commit()
            try:
                self._live = _Recording(identifier, where)
                self._live.start()
            except Exception as exc:
                self._live = None
                self._fail(identifier, f"{type(exc).__name__}: {exc}"[:300])
                raise MeetingError(f"the recording could not start: {exc}") from exc
        log.info("recording meeting %s", identifier)
        return self.get(identifier)

    def now(self) -> dict[str, Any]:
        """What the indicator draws. Always answers, even when nothing runs."""
        live = self._live
        if live is None:
            return {"recording": False}
        return {
            "recording": True,
            "id": live.id,
            "seconds": live.seconds,
            # So "recording, but the microphone is muted" is something a person
            # can see rather than discover afterwards.
            "hearing_you": live.mic_peak > SILENCE_PEAK,
            "hearing_them": live.speaker_peak > SILENCE_PEAK,
        }

    def stop(self, meeting_id: str = "") -> dict[str, Any]:
        """Stop recording and start working it up. Returns straight away."""
        with self._lock:
            live = self._live
            if live is None or (meeting_id and live.id != meeting_id):
                raise MeetingError("nothing is being recorded")
            self._live = None
            seconds = live.seconds
            live.stop()
            self._db.execute(
                "UPDATE meetings SET state = 'transcribing', ended_at = ?, seconds = ? WHERE id = ?",
                (_now(), int(seconds), live.id),
            )
            self._db.commit()
        threading.Thread(
            target=self._work_up, args=(live.id, live.folder), name="marvi-meeting", daemon=True
        ).start()
        return self.get(live.id)

    # -- what came of it ------------------------------------------------------

    def _work_up(self, meeting_id: str, folder: Path) -> None:
        """Transcribe both sides, interleave them, then ask for a summary."""
        try:
            turns = self._turns(folder)
            with self._lock:
                self._db.executemany(
                    "INSERT INTO meeting_turns (meeting_id, at_seconds, speaker, text)"
                    " VALUES (?, ?, ?, ?)",
                    [(meeting_id, at, who, text) for at, who, text in turns],
                )
                self._db.commit()
            if not turns:
                self._finish(meeting_id, "", [], [])
                return
            summary, decisions, actions = self._read_back(turns)
            self._finish(meeting_id, summary, decisions, actions)
            self._file_actions(meeting_id, actions)
        except Exception as exc:
            log.warning("meeting %s could not be worked up: %s", meeting_id, str(exc)[:200])
            self._fail(meeting_id, f"{type(exc).__name__}: {exc}"[:300])

    def _turns(self, folder: Path) -> list[tuple[int, str, str]]:
        """Both sides cut into timed windows, transcribed, and interleaved."""
        if self.transcribe is None:
            raise MeetingError("there is no speech recogniser to transcribe with")
        found: list[tuple[int, str, str]] = []
        for speaker, name in (("you", "mic.wav"), ("them", "speakers.wav")):
            source = folder / name
            if not source.exists():
                continue
            for at, pcm in windows(source):
                said = (self.transcribe(pcm) or "").strip()
                if said:
                    found.append((at, speaker, said))
        # By when it was said, so the transcript reads as the meeting happened
        # rather than as one monologue followed by another.
        found.sort(key=lambda row: (row[0], row[1]))
        return found

    def _read_back(self, turns: list[tuple[int, str, str]]) -> tuple[str, list[str], list[str]]:
        """The summary, the decisions and what is now owed, from a model."""
        from . import distil

        transcript = "\n".join(
            f"[{at // 60:02d}:{at % 60:02d}] {'You' if who == 'you' else 'Them'}: {text}"
            for at, who, text in turns
        )[:60_000]
        answer = distil.ask(
            self.client,
            "aux",
            "You are reading a meeting transcript. 'You' is the person whose machine "
            "recorded it; 'Them' is everyone else, heard through the speakers. Answer "
            'with JSON only: {"summary": "<a short paragraph>", "decisions": ["..."], '
            '"actions": ["..."]}. A decision is something settled, not discussed. An '
            "action is something a person now owes, written as an instruction and "
            "naming who owes it when the transcript says. Use [] when there are none; "
            "do not invent either.",
            transcript,
            max_tokens=900,
            tools=False,
        )
        return _parsed(answer)

    def _file_actions(self, meeting_id: str, actions: list[str]) -> None:
        """Action items become cards, because a list nobody opens again is a
        list that may as well not exist."""
        if self.board is None:
            return
        title = self.get(meeting_id)["title"]
        for action in actions[:20]:
            try:
                self.board.add(action, f"From the meeting: {title}", assignee="owner",
                               created_by="marvi")
            except Exception as exc:
                log.info("an action item did not reach the board: %s", str(exc)[:160])

    def _finish(self, meeting_id: str, summary: str, decisions: list[str], actions: list[str]) -> None:
        with self._lock:
            self._db.execute(
                "UPDATE meetings SET state = 'ready', summary = ?, decisions = ?, actions = ?"
                " WHERE id = ?",
                (summary, json.dumps(decisions), json.dumps(actions), meeting_id),
            )
            self._db.commit()

    def _fail(self, meeting_id: str, detail: str) -> None:
        with self._lock:
            self._db.execute(
                "UPDATE meetings SET state = 'failed', detail = ? WHERE id = ?",
                (detail, meeting_id),
            )
            self._db.commit()

    # -- reading --------------------------------------------------------------

    def get(self, meeting_id: str, turns: bool = True) -> dict[str, Any]:
        row = self._db.execute("SELECT * FROM meetings WHERE id = ?", (meeting_id,)).fetchone()
        if row is None:
            raise KeyError(f"no meeting called {meeting_id}")
        found = dict(row)
        found["decisions"] = json.loads(found["decisions"] or "[]")
        found["actions"] = json.loads(found["actions"] or "[]")
        if turns:
            found["turns"] = [
                dict(one)
                for one in self._db.execute(
                    "SELECT at_seconds, speaker, text FROM meeting_turns"
                    " WHERE meeting_id = ? ORDER BY at_seconds, id",
                    (meeting_id,),
                )
            ]
        return found

    def all(self, limit: int = 40) -> list[dict[str, Any]]:
        return [
            self.get(str(row["id"]), turns=False)
            for row in self._db.execute(
                "SELECT id FROM meetings ORDER BY started_at DESC LIMIT ?", (max(1, limit),)
            )
        ]

    def transcript(self, meeting_id: str) -> str:
        """The whole thing as text, for attaching to a message."""
        found = self.get(meeting_id)
        lines = [f"{found['title']} -- {found['started_at']}", ""]
        lines += [
            f"[{turn['at_seconds'] // 60:02d}:{turn['at_seconds'] % 60:02d}] "
            f"{'You' if turn['speaker'] == 'you' else 'Them'}: {turn['text']}"
            for turn in found.get("turns", [])
        ]
        return "\n".join(lines)

    def remove(self, meeting_id: str) -> bool:
        """Forget it, recordings included."""
        try:
            folder = Path(self.get(meeting_id, turns=False)["folder"])
        except KeyError:
            return False
        with self._lock:
            self._db.execute("DELETE FROM meeting_turns WHERE meeting_id = ?", (meeting_id,))
            gone = self._db.execute("DELETE FROM meetings WHERE id = ?", (meeting_id,)).rowcount
            self._db.commit()
        if folder.is_dir():
            import shutil

            shutil.rmtree(folder, ignore_errors=True)
        return bool(gone)

    def recover(self) -> int:
        """A meeting the Gateway was recording when it died is not recording.

        Its audio is on disk and is worth keeping, so the card is corrected to
        `failed` with a reason rather than left claiming to be live forever.
        """
        stuck = [
            str(row["id"])
            for row in self._db.execute("SELECT id FROM meetings WHERE state = 'recording'")
        ]
        for meeting_id in stuck:
            self._fail(meeting_id, "the Gateway restarted while this was recording")
        return len(stuck)

    def close(self) -> None:
        if self._live is not None:
            self._live.stop()
            self._live = None
        self._db.close()


def _parsed(answer: str) -> tuple[str, list[str], list[str]]:
    """The model's JSON, or nothing. Never raises: a meeting with no summary is
    still a meeting with a transcript."""
    text = (answer or "").strip()
    if text.startswith("```"):
        text = text.strip("`")
        text = text.split("\n", 1)[-1] if "\n" in text else text
    start, end = text.find("{"), text.rfind("}")
    if start < 0 or end <= start:
        return "", [], []
    try:
        got = json.loads(text[start : end + 1])
    except ValueError:
        return "", [], []
    if not isinstance(got, dict):
        return "", [], []
    lists = (
        [str(one)[:300] for one in got.get(key, []) if str(one).strip()]
        if isinstance(got.get(key), list)
        else []
        for key in ("decisions", "actions")
    )
    decisions, actions = lists
    return str(got.get("summary") or "")[:4000], decisions, actions


def windows(source: Path) -> list[tuple[int, bytes]]:
    """One side of the call, cut into timed pieces, silence left out.

    `(the second it starts at, its PCM)`. Silence is skipped rather than
    transcribed: one side of a call is quiet for most of it, and that quiet is
    most of what transcribing the whole thing would cost.
    """
    import numpy

    made: list[tuple[int, bytes]] = []
    with wave.open(str(source), "rb") as handle:
        rate = handle.getframerate()
        per_window = rate * WINDOW_SECONDS
        index = 0
        while True:
            frames = handle.readframes(per_window)
            if not frames:
                break
            at = index * WINDOW_SECONDS
            index += 1
            samples = numpy.frombuffer(frames, dtype=numpy.int16)
            if not samples.size or int(abs(samples.astype(numpy.int32)).max()) < SILENCE_PEAK:
                continue
            made.append((at, frames))
    return made


class _Recording:
    """Two streams and two WAV files, for as long as the meeting lasts."""

    def __init__(self, identifier: str, folder: Path) -> None:
        self.id = identifier
        self.folder = folder
        self.started = datetime.now(UTC)
        self._files: dict[str, wave.Wave_write] = {}
        self._captures: list[audiocapture.Capture] = []
        self._lock = threading.Lock()
        self._guard: threading.Timer | None = None

    @property
    def seconds(self) -> float:
        return (datetime.now(UTC) - self.started).total_seconds()

    @property
    def mic_peak(self) -> int:
        return max((one.peak for one in self._captures if not one.speakers), default=0)

    @property
    def speaker_peak(self) -> int:
        return max((one.peak for one in self._captures if one.speakers), default=0)

    def start(self) -> None:
        for speakers, name in ((False, "mic.wav"), (True, "speakers.wav")):
            # Held open for the length of the meeting rather than per write:
            # a `with` here would close it after the first chunk.
            handle = wave.open(str(self.folder / name), "wb")  # noqa: SIM115
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(audiocapture.TARGET_RATE)
            self._files[name] = handle
            capture = audiocapture.Capture(speakers, self._writer(name))
            try:
                capture.start()
            except Exception:
                self.stop()
                raise
            self._captures.append(capture)
        # A recording nobody stopped is the failure that matters here, so it
        # stops itself rather than filling a disk overnight.
        self._guard = threading.Timer(MAX_SECONDS, self.stop)
        self._guard.daemon = True
        self._guard.start()

    def _writer(self, name: str) -> Callable[[bytes], None]:
        def write(pcm: bytes) -> None:
            with self._lock:
                handle = self._files.get(name)
                if handle is not None:
                    handle.writeframes(pcm)

        return write

    def stop(self) -> None:
        if self._guard is not None:
            self._guard.cancel()
            self._guard = None
        for capture in self._captures:
            capture.stop()
        self._captures.clear()
        with self._lock:
            for handle in self._files.values():
                with contextlib.suppress(Exception):
                    handle.close()
            self._files.clear()


#: Words in a calendar entry that mean there is a meeting to be in.
_LINKS = ("meet.google.com", "zoom.us", "teams.microsoft.com", "teams.live.com", "webex.com")


def due(events: list[dict[str, Any]], at: datetime | None = None, within: int = 120) -> dict[str, Any] | None:
    """The calendar event worth offering to take notes on, if there is one.

    A meeting with somewhere to join, starting within a couple of minutes.
    Whole-day entries are not meetings, and an event with no link is one
    somebody is attending in a room where a laptop hears nothing useful.
    """
    when = at or datetime.now(UTC)
    for event in events:
        if event.get("all_day"):
            continue
        text = " ".join(str(event.get(key, "")) for key in ("title", "location", "id"))
        if not any(link in text.lower() for link in _LINKS):
            continue
        try:
            starts = datetime.fromisoformat(str(event["start"]))
        except (KeyError, ValueError):
            continue
        if starts.tzinfo is None:
            starts = starts.replace(tzinfo=UTC)
        if -within <= (starts - when).total_seconds() <= within:
            return {"id": str(event.get("id") or ""), "title": str(event.get("title") or "Meeting")}
    return None


def register_meeting_tools(registry: Any, store: Meetings) -> None:
    from .tools import ToolSpec
    from .untrusted import wrap_external

    def meeting_notes(meeting: str = "", limit: int = 5) -> dict[str, Any]:
        """What was said and decided. Never starts anything."""
        if meeting:
            try:
                found = store.get(meeting)
            except KeyError:
                return {"error": f"there is no meeting called {meeting}"}
            return {
                "title": found["title"],
                "state": found["state"],
                "summary": found["summary"],
                "decisions": found["decisions"],
                "actions": found["actions"],
                # The other people in the meeting are not the owner, and what
                # they said is information rather than instruction.
                "transcript": wrap_external(f"meeting:{meeting}", store.transcript(meeting)),
            }
        return {
            "meetings": [
                {k: one[k] for k in ("id", "title", "state", "started_at", "seconds", "summary")}
                for one in store.all(max(1, min(int(limit), 40)))
            ],
            "recording_now": store.now(),
        }

    registry.register(
        ToolSpec(
            name="meeting_notes",
            description="Read the notes from a recorded meeting, or list the recent ones.",
            arguments={},
            optional={"meeting": str, "limit": int},
            sensitive=False,
            handler=meeting_notes,
            describes={
                "meeting": "The id of one meeting, for its summary, decisions, actions and "
                "transcript. Left out, this lists the recent ones instead.",
                "limit": "How many to list when no meeting is named. At most 40.",
            },
        )
    )
