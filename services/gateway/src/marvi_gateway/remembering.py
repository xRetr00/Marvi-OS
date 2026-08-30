"""What Marvi remembers from a turn, decided after the turn.

Three things were wrong with how memory was written, and they were one thing:
the model did it, mid-conversation, by hand.

* **It happened during the turn.** Deciding to remember cost a tool call on the
  latency-critical path. Honcho stores the message and returns immediately --
  "nothing about the reasoning that follows blocks the caller" -- and Mem0 does
  the same. Marvi was the only one making you wait to be remembered.
* **It stored what the model typed.** No extraction pass, so a memory was
  whatever phrasing the model reached for. That is how `Hi Sharif.` became an
  episodic memory whose subject was "Hello": her own reply, filed as a fact
  about the world.
* **It could only add.** `remember` was an unconditional INSERT, so a
  correction joined the fact it corrected instead of replacing it -- five
  spellings of one name inside two minutes.

## Four operations, chosen by a model

Mem0's shape, because it is the right one and the failure it prevents is the
failure we had: the candidate fact is weighed against the memories nearest to
it and the answer is `add`, `update`, `delete` or `noop`, decided *at write
time* rather than left for recall to sort out.

The string-similarity supersede in `MemoryStore.remember` stays underneath as
the floor. It catches five spellings of a name; it cannot catch "I moved to
Cairo" superseding "lives in Alexandria", because those share no words. A model
can. When there is no model, the floor is what is left, and it is still better
than an append-only store.

## Off the turn

The queue is the point, not an optimisation. `observe()` returns as soon as the
turn is on it; a worker thread does the extraction whenever the model answers.
Nothing a user waits for is behind this.
"""

from __future__ import annotations

import json
import queue
import threading
import time
from typing import Any

from . import distil, observations
from .logs import get_logger
from .memory import SecretInMemoryError

log = get_logger("memory")

#: How many existing memories the model is shown when judging a new one.
#: Enough to spot the fact being corrected, few enough to stay cheap.
NEIGHBOURS = 8

#: A turn longer than this is trimmed. Extraction wants the gist; a model
#: reading a 4,000-word reply to find one fact is paying for the wrong thing.
MAX_TURN_CHARS = 4_000

MAX_OUTPUT_TOKENS = 700

#: Dropped rather than queued without limit. Falling behind on memory is
#: survivable; growing a queue until the process dies is not.
QUEUE_DEPTH = 32

SYSTEM_PROMPT = (
    "You decide what an assistant should remember from one exchange, and what "
    "to do about what it already remembers.\n"
    "Reply with a JSON array and nothing else. Each element is one operation:\n"
    '  {"op":"add","subject":"...","body":"...","kind":"semantic"}\n'
    '  {"op":"update","id":12,"subject":"...","body":"..."}\n'
    '  {"op":"delete","id":12}\n'
    "An empty array is the right answer most of the time. Reply [] unless the "
    "exchange contains something durably true about the user, their world, or "
    "their standing preferences.\n"
    "\n"
    # Measured, and the reason this is examples rather than another adjective.
    # The prompt said "durably true", and the model read a possession and a
    # visit as not durable enough: "I switched my editor to Zed" and "I am
    # allergic to penicillin" stored 5 times in 5, "I got a Keychron K2" zero
    # times in 5. Over five exchanges that should be kept and three that should
    # not, the shipped wording kept 17 of 25 and these examples keep 25 of 25 --
    # with the second column unchanged at 0 of 15 wrongly stored, which is the
    # column that matters. A variant that kept everything by also keeping
    # pleasantries would be worse than the one it replaced.
    "What counts. All of these are worth storing:\n"
    '  "I got a Keychron K2" -> the user owns a Keychron K2 keyboard\n'
    '  "my sister Nour is visiting" -> the user has a sister named Nour\n'
    '  "I switched my editor to Zed" -> the user uses Zed as their editor\n'
    '  "I start at 4am on Fridays" -> the user starts work at 4am Fridays\n'
    "\n"
    "A possession, a person in their life, a plan with a date, a tool they "
    "use, a health fact: all durable. The test is whether you would look "
    "foolish not knowing it next week, not whether it stays true forever.\n"
    "\n"
    # The owner found this before the tests did. Told out loud "I have a PS5
    # controller", the recogniser heard "BS5", nothing downstream was looking,
    # and the store held a product that does not exist -- ready to be said
    # back for as long as it was there. The recogniser cannot know a word it
    # has never seen; the vocabulary correction only knows names already in
    # memory, and this was the turn that would have added it. This is the
    # only place in the chain that knows what is and is not a real thing.
    "You are reading speech, and the recogniser gets names and products "
    "wrong. Write down what they meant rather than what it heard, when you "
    "are sure: a BS5 controller is a PlayStation 5 controller, Vercell is "
    "Vercel. Only when you are sure -- a name you do not recognise is "
    "usually one you do not know rather than one that was mis-heard, and "
    "inventing a correction is worse than storing an odd spelling.\n"
    "\n"
    "These are not memories:\n"
    '  "how are we doing?" -> nothing\n'
    '  "what do you know about X?" -> nothing, they are asking not telling\n'
    "\n"
    "Rules that matter:\n"
    "- `update` when the exchange corrects or refines an existing memory. Use "
    "it rather than `add`: a correction that is added sits beside the thing it "
    "was meant to replace, and both come back on recall.\n"
    "- `delete` only when a memory is now known to be false. Being out of date "
    "is what `update` is for.\n"
    "- Never store the assistant's own words, pleasantries, or the fact that a "
    "conversation happened. 'The user said hello' is not a memory.\n"
    "- Never store anything already true on every turn -- the user's name and "
    "standing preferences live in their identity file, not here.\n"
    "- A memory is one durable sentence stating what is true, not a summary of "
    "what was said.\n"
    "- Name the subject in words somebody would use to ask about it. A memory "
    "is written once as a statement and found later by a question, and the "
    "search only has the words in it: \"typically night shifts\" cannot be "
    "found by \"what is my schedule like\", because it contains no word "
    "anyone would search with. \"The user's working schedule is night shifts "
    "at a bakery\" can. Say the category out loud -- schedule, diet, health, "
    "budget, hardware -- as well as the particular.\n"
    "- `kind` is `semantic` for what is true and `episodic` for what happened. "
    "Prefer semantic; episodic entries expire."
)


def _turn_text(user: str, assistant: str) -> str:
    user, assistant = user.strip()[:MAX_TURN_CHARS], assistant.strip()[:MAX_TURN_CHARS]
    return f"User: {user}\n\nAssistant: {assistant}"


def _existing(store: Any, about: str = "") -> list[dict[str, Any]]:
    """The memories a new fact is most likely to be about.

    Searched, then topped up with recent ones. It used to be recent only, on
    the grounds that the search was keyword-only and a correction is routinely
    worded differently -- true when it was written, and no longer: the search
    has been hybrid since embeddings landed, so it now finds the memory this
    exchange is about even when the words differ.

    The change was not an improvement, it was a repair. `recent` is whatever
    was written last, and once a mailbox was connected that was nine marketing
    emails -- 3,927 characters of JSON bodies and tracking whitespace shown to
    the extractor before every exchange. Measured against the live store: the
    same two exchanges that produced an `add` each against an empty list both
    produced `[]` against that one. Marvi could not remember anything at all
    while a connector was writing, and nothing said so; the worker ran, cost a
    model call per turn, and stored nothing.

    Searching first means an ingest burst can no longer crowd out the
    conversation, because what is listed is chosen by the exchange rather than
    by whatever arrived most recently.
    """
    found: list[dict[str, Any]] = []
    seen: set[Any] = set()
    for source in (
        (lambda: store.search(about, limit=NEIGHBOURS)) if about.strip() else (lambda: []),
        lambda: store.recent(limit=NEIGHBOURS),
    ):
        try:
            rows = source()
        except Exception:  # pragma: no cover - depends on the store
            continue
        for row in rows:
            if row.get("id") in seen:
                continue
            seen.add(row.get("id"))
            found.append(row)
    return found[:NEIGHBOURS]


def _parse(text: str) -> list[dict[str, Any]]:
    """Operations from a model's reply, or none.

    Never raises. This runs on a worker thread behind a queue; a malformed
    answer means nothing is remembered from one turn, which is a far better
    outcome than a thread that dies and takes every later turn with it.
    """
    body = (text or "").strip().strip("`")
    if body.lower().startswith("json"):
        body = body[4:].strip()
    start, end = body.find("["), body.rfind("]")
    if start < 0 or end <= start:
        return []
    try:
        parsed = json.loads(body[start : end + 1])
    except ValueError:
        return []
    return [item for item in parsed if isinstance(item, dict)] if isinstance(parsed, list) else []


def apply(store: Any, operations: list[dict[str, Any]]) -> dict[str, Any]:
    """Carry out what the model decided. Returns what was done, by operation.

    `noted` carries the subjects, not just the counts, because Marvi is told
    what she recorded on the next turn and "I noted 2 things" is not something
    a person can correct.
    """
    done: dict[str, Any] = {"add": 0, "update": 0, "delete": 0, "ignored": 0, "noted": []}
    for operation in operations:
        name = str(operation.get("op") or "").strip().lower()
        body = str(operation.get("body") or "").strip()
        subject = str(operation.get("subject") or "").strip()
        kind = "episodic" if str(operation.get("kind")) == "episodic" else "semantic"
        try:
            if name == "add" and body and subject:
                store.remember(subject, body, kind=kind)
                done["add"] += 1
                done["noted"].append(subject)
            elif name == "update" and body and operation.get("id") is not None:
                # Through `forget` and `remember` rather than a bespoke write,
                # so the FTS index and the supersede floor both still apply.
                store.forget(int(operation["id"]))
                store.remember(subject or body[:60], body, kind=kind)
                done["update"] += 1
                done["noted"].append(f"{subject or body[:60]} (corrected)")
            elif name == "delete" and operation.get("id") is not None:
                store.forget(int(operation["id"]))
                done["delete"] += 1
            else:
                done["ignored"] += 1
        except SecretInMemoryError:
            # The prompt above tells the model not to extract these. This is
            # what happens when it does anyway, which is why the store refuses
            # rather than trusting the instruction.
            log.warning("a proposed memory carried a credential and was dropped")
            done["ignored"] += 1
        except Exception as exc:  # pragma: no cover - depends on the store
            log.warning("memory operation failed: %s", exc, extra={"marvi_op": name})
            done["ignored"] += 1
    return done


def extract(store: Any, client: Any, user: str, assistant: str) -> dict[str, int]:
    """Decide and apply what to remember from one exchange.

    Synchronous, so it can be tested without a queue. `observe` is what
    callers use.
    """
    if client is None or not (user.strip() or assistant.strip()):
        return {"add": 0, "update": 0, "delete": 0, "ignored": 0}

    known = _existing(store, _turn_text(user, assistant))
    listed = (
        "\n".join(
            f"[{row['id']}] ({row['kind']}) {row['subject']}: {row['body']}" for row in known
        )
        or "(nothing remembered yet)"
    )
    try:
        # One place knows a "client" may be a ProviderClient or the harness
        # wrapping one. This had its own copy of the call and assumed the raw
        # client, so being handed the harness -- which is what the app does --
        # made every turn raise AttributeError into the except below and log
        # "unavailable". It did that for a day.
        #
        # `tools=False`: it has to come back as JSON. A model offered the
        # memory tools alongside a schema will sometimes write the memory
        # itself and answer nothing, which is the operation this replaces,
        # done worse and without the delete.
        answer = distil.ask(
            client,
            "memory",
            SYSTEM_PROMPT,
            f"Already remembered:\n{listed}\n\n"
            f"The exchange:\n{_turn_text(user, assistant)}",
            MAX_OUTPUT_TOKENS,
            tools=False,
            temperature=0.1,
        )
    except Exception as exc:
        log.info("memory extraction unavailable (%s); nothing recorded this turn", exc)
        return {"add": 0, "update": 0, "delete": 0, "ignored": 0}

    operations = _parse(answer)
    done = apply(store, operations)
    if any(done.values()):
        log.info(
            "memory: %d added, %d updated, %d deleted",
            done["add"],
            done["update"],
            done["delete"],
            extra={"marvi_route": "auxiliary/memory", "marvi_considered": str(len(known))},
        )
    observations.record(
        "store",
        said=user,
        add=done.get("add", 0),
        update=done.get("update", 0),
        delete=done.get("delete", 0),
        neighbours=len(known),
    )
    return done


class Rememberer:
    """A worker that reads turns off a queue and decides what to keep.

    One thread, because the work is a single model call and ordering matters:
    two extractions racing on the same store could each decide to correct the
    same memory and one would win by scheduling.

    ## Its own connection

    The worker opens its own `MemoryStore` rather than sharing the caller's. A
    `sqlite3.Connection` is not safe to use from two threads at once even with
    `check_same_thread=False`, and sharing one crashed the test suite with a
    Windows access violation -- not an exception, a segfault, surfacing inside
    pytest's unrelated path handling. One connection per thread avoids the
    whole class.

    ## Started on demand

    The thread starts with the first turn rather than at construction. Every
    `create_app()` builds one of these, including the several hundred a test
    run builds, and a daemon thread each was a thread each.
    """

    def __init__(
        self,
        store: Any,
        client: Any,
        *,
        propose_skills: bool = True,
        observe_callback: Any = None,
    ) -> None:
        self._store = store
        self._client = client
        #: What the last completed turn was recorded as, until somebody reads
        #: it. Held rather than logged because the point is that Marvi learns
        #: of it: the write happens off the turn, so without this she has no
        #: idea a memory was made and cannot be corrected about it in the
        #: moment -- the loop closed silently, a turn late.
        self.noted: list[str] = []
        # External memory providers own extraction. The same ordered worker is
        # retained so provider I/O stays off the reply path and skill proposals
        # still happen once per completed turn.
        self._observe_callback = observe_callback
        #: Whether the same pass also asks "should a skill be written?".
        #: A second model call per turn, off the turn, and worth it: a
        #: correction about *how* Marvi works has nowhere else to go -- memory
        #: holds facts about the world and the prompt is fixed, so the same
        #: mistake returns next session.
        self._propose_skills = propose_skills
        #: What the last turn suggested writing down, waiting for a person.
        #: One slot: two unreviewed proposals is a queue nobody empties.
        self.proposal: dict[str, Any] | None = None
        self._turns: queue.Queue[tuple[str, str]] = queue.Queue(maxsize=QUEUE_DEPTH)
        #: Set while a turn is being extracted, so `drain` can tell "nothing
        #: queued" from "nothing queued and nothing in flight".
        self._working = threading.Event()
        self._thread: threading.Thread | None = None
        self._starting = threading.Lock()

    def _ensure_running(self) -> None:
        with self._starting:
            if self._thread is None or not self._thread.is_alive():
                self._thread = threading.Thread(
                    target=self._run, name="marvi-memory", daemon=True
                )
                self._thread.start()

    def _own_store(self) -> Any:
        """A private connection to the same database, for this thread."""
        path = getattr(self._store, "path", None)
        if path is None:
            return self._store
        from .memory import MemoryStore

        return MemoryStore(path)

    def observe(self, user: str, assistant: str) -> bool:
        """Hand over a finished turn. Never blocks; False when the queue is full."""
        self._ensure_running()
        try:
            self._turns.put_nowait((user, assistant))
            return True
        except queue.Full:
            # Said out loud rather than swallowed. A memory quietly not written
            # is the failure this whole module exists to fix.
            log.warning("memory queue is full; this turn will not be remembered")
            return False

    def _run(self) -> None:
        mine = self._own_store()
        while True:
            user, assistant = self._turns.get()
            self._working.set()
            try:
                if self._observe_callback is None:
                    result = extract(mine, self._client, user, assistant)
                    # Kept short. This goes in front of a model on the next
                    # turn, and three things she has just written down is
                    # already more than a spoken sentence can carry.
                    self.noted = list(result.get("noted") or [])[:3]
                else:
                    self._observe_callback(user, assistant)
                if self._propose_skills:
                    self._review_skills(user, assistant)
            except Exception as exc:  # pragma: no cover - the thread must survive
                log.warning("memory worker recovered from: %s", exc)
            finally:
                self._working.clear()
                self._turns.task_done()

    def _review_skills(self, user: str, assistant: str) -> None:
        """Ask whether this turn taught something worth writing down.

        Proposed rather than written. A skill is instructions Marvi will follow
        later, so a model that can write one silently is a model that can
        rewrite its own behaviour -- and the Skills page already has a review
        flow, because that argument was settled when skills became installable
        from a store.
        """
        from . import learning
        from .setup import skills as skills_module

        try:
            available = skills_module.installed()
        except Exception:  # pragma: no cover - depends on what is on disk
            available = []
        found = learning.propose(self._client, user, assistant, available)
        if found:
            self.proposal = found
            log.info(
                "skill proposed: %s %s -- %s",
                found["act"],
                found["name"],
                found["why"],
                extra={"marvi_skill": found["name"], "marvi_act": found["act"]},
            )

    def take_notes(self) -> list[str]:
        """What was recorded since this was last asked, then forget it.

        Read once. A line saying "you noted X" belongs on the turn after X was
        written and on no turn after that -- repeating it would have her
        announcing the same memory until something else replaced it.
        """
        noted, self.noted = self.noted, []
        return noted

    def drain(self, timeout: float = 5.0) -> bool:
        """Wait for what is queued. For tests, and for a clean shutdown.

        Returns whether it emptied. Bounded rather than `Queue.join()`, because
        a worker wedged on a model that never answers must not hold a shutdown
        open for ever.
        """
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            if self._turns.empty() and not self._working.is_set():
                return True
            time.sleep(0.02)
        return False
