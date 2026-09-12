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
import re
import threading
import time
from typing import Any

from . import distil, observations, prompts
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

SYSTEM_PROMPT = prompts.text("memory-extraction")


#: How much of Marvi's reply the extractor sees. Enough to know what "yes"
#: agreed to; not the tool results and room readings a long reply carries,
#: which is where "Light is off", "revision 2" and "it is currently 11 PM"
#: were being lifted from and filed as facts about the user.
REPLY_CONTEXT_CHARS = 600


def _turn_text(user: str, assistant: str) -> str:
    user = user.strip()[:MAX_TURN_CHARS]
    assistant = assistant.strip()
    if len(assistant) > REPLY_CONTEXT_CHARS:
        assistant = assistant[:REPLY_CONTEXT_CHARS].rsplit(" ", 1)[0] + " ..."
    return f"User: {user}\n\nAssistant (context only, not a source of facts): {assistant}"


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


#: A memory that describes the conversation instead of the world.
#:
#: The prompt already forbids this, in those words -- "Never store the
#: assistant's own words, pleasantries, or the fact that a conversation
#: happened. 'The user said hello' is not a memory." -- and the model wrote
#: these anyway, 55 of them:
#:
#:   User's greeting and status | The user said 'Yeah, I was wondering I was
#:                                going on.' which Marvi interpreted as a
#:                                greeting or status update.
#:   User checking on assistant | The user confirmed they were checking on the
#:                                assistant's status.
#:   User's farewell ...        | The user said 'Thank you, no singles. You can
#:                                end up in.' and the assistant responded with
#:                                'Goodnight, Shereef.'
#:
#: Every one built out of a misheard sentence, and every one of them then
#: coming back on recall as though it bore on the turn. Compare what the same
#: store holds from the dreaming pass, which is what a memory should look like:
#: "Shereef uses Home Assistant for home automation and has a RGBCW lightbulb
#: (entity_id light.rgbcw_lightbulb) in their room."
#:
#: So it is refused here rather than asked for politely, which is the same
#: choice already made for credentials: the store does not trust the
#: instruction, it checks. A rule the model ignores is not a rule.
NARRATES_THE_EXCHANGE = re.compile(
    # A speech verb, not merely the word "assistant". Written the broad way
    # first, and a dry run over the real store showed what that costs:
    #
    #   "The backend infrastructure of the assistant system is named Hermes"
    #   "Gmail requires re-authentication, and the assistant cannot check email"
    #
    # Both real facts, both about the assistant rather than about something it
    # said, and both would have been thrown away. What makes a row worthless is
    # that it narrates the exchange -- somebody saying something -- so that is
    # what this matches and nothing wider.
    r"\bthe (?:user|assistant) (?:said|asked|replied|responded|confirmed"
    r"|mentioned|stated|indicated|greeted|told)\b"
    # The progressive forms, which the past tense alone missed. This one got
    # through and was kept as a memory:
    #
    #   Shereef's games | "The user is asking about things related to a game,
    #                     but the specific game is not yet known."
    #
    # A note that says it does not know the thing it is about is not a fact
    # about the world; it is a transcript of a moment of confusion.
    r"|\bthe (?:user|assistant) (?:is|was|has been) (?:asking|telling|saying"
    r"|talking|referring|wondering|inquiring)\b"
    r"|\b(?:is |are )?not (?:yet )?(?:known|clear|specified|determined)\b"
    r"|\b(?:which|this) indicates\b"
    r"|\bmarvi (?:interpreted|responded|replied|said)\b",
    re.IGNORECASE,
)


#: True now and not next week: device, room and machine state, the time.
#:
#: Measured on the owner's store on 12 September, where 25 memories were this
#: kind -- "Light is off. The Tuya bulb's circuit breaker is open", "No alarms
#: are active in the room", "The user's cursor is at screen coordinates (1362,
#: 742)", "It is currently 11 PM" -- and every one came back on recall into
#: turns where it had long stopped being true. "Room sidecar process down" was
#: still being recalled, at strength 44, days after it was fixed. "Currently
#: lives in" is exempt: that is where somebody lives.
PASSING_STATE = re.compile(
    r"\bcurrently\b(?! (?:lives?|living|works?|working|studies|studying|based|employed|owns?))"
    r"|\b(?:right now|at the moment|just now|is (?:still|now) (?:starting|loading|running))\b"
    r"|\bcurrent (?:state|status|activity|time|location|device|weather|light)\b"
    r"|\b(?:light|lamp|bulb) is (?:on|off)\b|\bcircuit breaker\b"
    r"|\bbattery (?:level )?(?:is )?(?:at )?\d|\b\d+% (?:battery|brightness)\b|\bare all online\b"
    r"|\btemperature is \d|\bmode is (?:normal|off|sleep|focus|relax|reading)\b"
    r"|\bcursor (?:is )?at\b|\bscreen coordinates\b"
    r"|\bno alarms are active\b|\bunreported (?:visitor )?entr"
    r"|\b(?:process|sidecar|daemon|driver|browser|gateway|agent)\b[^.]{0,40}\b(?:is|was) "
    r"(?:down|running|not ready|starting up|not showing)\b"
    r"|\b(?:devices?|systems?) (?:are|is) (?:all )?(?:online|up|running)\b"
    r"|\brevision \d+\b|\bsession [0-9a-f]{12,}\b",
    re.IGNORECASE,
)

#: The assistant's account of its own attempts, tools and delays -- 17 of them
#: on the same day, "The assistant attempted to navigate the browser to
#: https://google.com using session 53b2... (revision 2)" among them. What she
#: did in a turn is the transcript's business, not memory's.
ITS_OWN_DOING = re.compile(
    r"^(?:the )?assistant(?:'s)? (?:attempted|tried|was delayed|is (?:taking|trying|opening|attempting|finding)"
    r"|took|plans?|has found|demonstrated|checked its|successfully ran|will report)"
    r"|\bthe assistant'?s? (?:computer |alarm )?tools? (?:are|is|were) (?:rejecting|failing)"
    r"|\b(?:jarvi|harvi|talos)\b[^.]{0,60}\b(?:task|is (?:on it|opening|moving)|completed moving)\b"
    r"|\bwas delayed because it was answering\b|\bdemo (?:attempt )?failed\b",
    re.IGNORECASE,
)


def not_a_memory(subject: str, body: str) -> str:
    """Why this is not worth keeping, or empty when it is.

    Shared by the writer, recall and dreaming: a store keeps what it was given,
    so what the writer now refuses must also stop coming back from before it
    did, and a conclusion drawn from such rows is no better than they were.
    """
    body = " ".join((body or "").split())
    if NARRATES_THE_EXCHANGE.search(body):
        return "describes the conversation"
    if ITS_OWN_DOING.search(body) or ITS_OWN_DOING.search(subject or ""):
        return "describes what the assistant did"
    if PASSING_STATE.search(f"{subject}. {body}"):
        return "only true right now"
    return ""


def apply(store: Any, operations: list[dict[str, Any]]) -> dict[str, Any]:
    """Carry out what the model decided. Returns what was done, by operation.

    `noted` carries the subjects, not just the counts, because Marvi is told
    what she recorded on the next turn and "I noted 2 things" is not something
    a person can correct.
    """
    done: dict[str, Any] = {"add": 0, "update": 0, "delete": 0, "ignored": 0, "noted": []}
    for operation in operations:
        name = str(operation.get("op") or "").strip().lower()
        # `str()` on whatever arrived is how two memories came to have a Python
        # dict repr for a body:
        #
        #     subject: User shared a link
        #     body:    {'id': 'User shared a link'}
        #
        # The model answered with an object where a sentence belongs and
        # `str(dict)` took it without complaint, so the store held a row that
        # can never be recalled usefully and reads as corruption. A body that
        # is not a string is not a body.
        raw_body, raw_subject = operation.get("body"), operation.get("subject")
        if (raw_body is not None and not isinstance(raw_body, str)) or (
            raw_subject is not None and not isinstance(raw_subject, str)
        ):
            log.warning(
                "a proposed memory had a %s where text belongs; dropped",
                type(raw_body if not isinstance(raw_body, str) else raw_subject).__name__,
            )
            done["ignored"] += 1
            continue
        body = (raw_body or "").strip()
        subject = (raw_subject or "").strip()
        kind = "episodic" if str(operation.get("kind")) == "episodic" else "semantic"
        refused = not_a_memory(subject, body) if body and name in ("add", "update") else ""
        if refused:
            # Loudly. The whole reason this went unnoticed for 55 memories is
            # that nothing anywhere said a word about them.
            log.warning(
                "a proposed memory %s rather than a fact; dropped: %r",
                refused if refused != "describes the conversation" else "described the conversation",
                f"{subject}: {body}"[:160],
            )
            done["ignored"] += 1
            continue
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


#: Words that carry no fact. The recall side of memory has had this list since
#: it was measured; the write side never got one.
ACKNOWLEDGEMENTS = frozenset(
    {
        "yeah", "yes", "yep", "yup", "ok", "okay", "sure", "right", "fine", "good",
        "great", "nice", "cool", "no", "nope", "nah", "not", "really", "thanks",
        "thank", "you", "cheers", "please", "hmm", "huh", "oh", "ah", "ha", "uh",
        "um", "mhm", "mm", "go", "ahead", "carry", "on", "continue", "keep",
        "going", "got", "it", "i", "see", "makes", "sense", "sounds", "exactly",
        "correct", "true", "and", "so", "then", "well", "but", "just", "now",
        "still", "also", "very", "bye", "goodbye", "hi", "hello", "hey", "morning",
        "night", "sorry", "welcome",
    }
)


def worth_extracting(user: str, assistant: str) -> bool:
    """Whether this exchange could contain anything to remember.

    The mirror of the Agent's `needs_memory`, which decides whether a turn is
    worth *searching* memory for. The writing side never had one: every turn
    with any text at all bought a model call to decide what to remember,
    including "okay", "thanks" and "yeah, go ahead".

    That is two model calls per turn -- this one and the skill review below it
    -- on the turns least likely to contain a fact. Off the latency path, since
    both run on a worker thread, and squarely on the token budget, which is the
    thing that then runs out and silences the events that mattered.

    Only what the *user* said is examined. What Marvi said back is not a source
    of facts about the user, and a long helpful answer to "thanks" should not
    make a bare acknowledgement look substantial.
    """
    words = re.findall(r"[\w']+", (user or "").lower())
    if not words:
        return False
    return not all(word in ACKNOWLEDGEMENTS for word in words)


def extract(store: Any, client: Any, user: str, assistant: str) -> dict[str, int]:
    """Decide and apply what to remember from one exchange.

    Synchronous, so it can be tested without a queue. `observe` is what
    callers use.
    """
    if client is None or not (user.strip() or assistant.strip()):
        return {"add": 0, "update": 0, "delete": 0, "ignored": 0}
    if not worth_extracting(user, assistant):
        log.info("memory: nothing in this turn to write down; not asking a model")
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
                if self._propose_skills and worth_extracting(user, assistant):
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
