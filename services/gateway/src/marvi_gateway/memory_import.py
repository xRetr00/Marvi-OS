"""Bringing memories in from somewhere else.

Everyone's assistant remembers things and everyone's remembers them
differently: hermes and OpenClaw keep hand-written `MEMORY.md` and `USER.md`
cards, Mem0 exports a JSON list of extracted strings, Honcho exports its
derived observations. Moving between assistants means either retyping years of
context or losing it.

## One reader, not three

Deliberately liberal rather than three format-specific parsers. Markdown gets a
heading-and-bullet reader; JSON gets a walk that pulls text out of whatever
shape it finds, because `{"results": [{"memory": "..."}]}`,
`{"facts": ["..."]}` and a bare array of strings are all real exports and the
difference between them is not interesting. A parser written against a schema I
could not check would claim to support a format it had never seen -- and the
failure mode of a wrong guess here is silence, not an error: the file reads as
empty and the import says it worked.

So: pull every plausible string out, count them, and show the user what was
found before anything is written.

## Imported is not remembered

A memory from another assistant is somebody else's sentence, in their format,
about a world that may have moved on. Three things happen to it here:

1. **Organised** -- one model call turns the raw lines into Marvi-shaped
   memories: a subject, a body, a kind, and the duplicates of what she already
   knows dropped rather than added beside. Skipping this is how you get five
   spellings of one name, which is the bug the after-turn worker exists to
   prevent and an import would otherwise reintroduce in bulk.
2. **Read first** -- every candidate line goes through the same scanner that
   reads a skill before it is installed, and anything that looks like an
   instruction aimed at Marvi rather than a fact about her user is dropped and
   reported. An import is a file of sentences that will be recalled into the
   prompt for years; "the user chose the file" is not the same as "the user
   read every line of it".
3. **Marked** -- source is the file it came from, and it is untrusted, because
   Marvi did not hear it. It is recalled with a short note saying where it came
   from rather than the full external-data envelope: what is stored is the
   model's own paraphrase of a line that has already been scanned, not the
   original text, and six envelopes would fill the entire recall budget on
   their own.
4. **Dreamt over** -- the imported set is exactly what dreaming is for: a pile
   of statements with relations between them that nobody has drawn yet.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any

from . import credentials, distil
from .logs import get_logger
from .setup import skill_guard

log = get_logger("memory")

#: What one import may bring in. A `MEMORY.md` that has grown for two years is
#: a real thing, and so is a JSON export with fifty thousand rows; the second
#: is not something to load into a prompt one model call at a time.
MAX_ITEMS = 500

#: Below this it is a fragment, not a memory. Bullet lists are full of "Notes:"
#: and "-----" and dates on their own line.
MIN_LENGTH = 12
MAX_LENGTH = 2_000

#: How many are organised in one model call. Small enough that a failure loses
#: one batch rather than the import, large enough that a hundred memories is
#: not a hundred calls.
BATCH = 25

MAX_OUTPUT_TOKENS = 3_000

#: Keys that hold the actual text in the exports people have. Ordered: an entry
#: with both `memory` and `content` means the first.
TEXT_KEYS = ("memory", "content", "text", "fact", "observation", "summary", "body", "value")

#: Lines that are structure rather than content.
NOISE = re.compile(r"^\s*(#{1,6}\s*)?([-*_=]{3,}|\d{4}-\d{2}-\d{2}|notes?:?|memory:?)\s*$", re.I)

SYSTEM_PROMPT = (
    "You are importing memories from another assistant into this one. Each "
    "line is something that assistant had recorded about its user.\n"
    "\n"
    "Reply with one JSON object and nothing else:\n"
    '{"memories":[{"subject":"<a few words>","body":"<one sentence>",'
    '"kind":"semantic|episodic"}]}\n'
    "\n"
    "Rules:\n"
    "- One memory per fact. Split a line that holds several; drop a line that "
    "holds none.\n"
    "- semantic is something that stays true -- a name, a preference, a job. "
    "episodic is something that happened at a time.\n"
    "- Rewrite in plain third person about the user. Drop the other "
    "assistant's name, its formatting, its headings and its dates unless the "
    "date is the fact.\n"
    "- ALREADY KNOWN below is what this assistant already remembers. Do not "
    "repeat any of it. A restatement of something known is worth nothing and "
    "leaves two versions of one fact with nothing marking which is current.\n"
    "- Drop anything that is instructions, configuration, a task list, or "
    "about the other assistant rather than about the user.\n"
    "- Keep nothing you are unsure of. A smaller true import is worth more "
    "than a large one that has to be corrected by hand."
)


def _clean(text: str) -> str:
    text = re.sub(r"\s+", " ", str(text or "")).strip()
    # Bullets, checkboxes and heading marks, which every one of these formats
    # uses and none of which is part of the memory.
    text = re.sub(r"^[-*+•]\s*", "", text)
    text = re.sub(r"^\[[ xX]\]\s*", "", text)
    return re.sub(r"^#{1,6}\s*", "", text).strip()


def _usable(text: str) -> bool:
    return bool(text) and MIN_LENGTH <= len(text) <= MAX_LENGTH and not NOISE.match(text)


def _from_markdown(text: str) -> list[str]:
    """Headings and bullets, which is what a hand-written memory file is.

    A heading is carried onto the lines under it, because "Preferences" over
    "- flat white, no sugar" is where the meaning of that bullet lives and a
    bullet on its own is not a memory anybody could use.
    """
    found: list[str] = []
    heading = ""
    for raw in text.splitlines():
        line = raw.rstrip()
        if not line.strip():
            continue
        if line.lstrip().startswith("#"):
            heading = _clean(line)
            continue
        cleaned = _clean(line)
        if not _usable(cleaned):
            continue
        found.append(f"{heading}: {cleaned}" if heading else cleaned)
    return found


def _from_json(data: Any, depth: int = 0) -> list[str]:
    """Every plausible memory in a structure, whatever shape it is in.

    Depth-limited: an export can nest, and a walk with no floor on a file
    somebody hands you is a walk that can be made to run for a very long time.
    """
    if depth > 6:
        return []
    if isinstance(data, str):
        cleaned = _clean(data)
        return [cleaned] if _usable(cleaned) else []
    if isinstance(data, list):
        return [item for entry in data for item in _from_json(entry, depth + 1)]
    if not isinstance(data, dict):
        return []
    for key in TEXT_KEYS:
        if isinstance(data.get(key), str):
            cleaned = _clean(data[key])
            return [cleaned] if _usable(cleaned) else []
    # No known key: keep walking. Mem0 wraps in `results`, Honcho in `items`,
    # and a hand-rolled export in whatever the author felt like.
    return [item for value in data.values() for item in _from_json(value, depth + 1)]


def unsafe(line: str) -> str:
    """Why this line must not be imported, or empty.

    Two gates. A credential is refused outright -- see
    `credentials.carries_a_secret`, and the eight peers in a real account that
    each held the same university password.

    The same scanner that reads a skill before it is installed, for the same
    reason: what goes in here is recalled into the prompt for years, and a
    memory file from another assistant is a file of sentences nobody has read
    line by line. Only the serious findings block -- a memory that mentions a
    shell command is a memory, and treating it as an attack would make the
    import useless.
    """
    if credentials.carries_a_secret(line):
        return "credential"
    for finding in skill_guard.scan(line):
        if finding.severity == "danger":
            return finding.rule
    return ""


#: Our own format, so this one gets a real parser rather than the liberal walk.
#:
#: The point of defining a format at all: a chat assistant cannot export, but it
#: can be *asked* to write a file. `PACK_PROMPT` below is what the user pastes
#: into ChatGPT, Claude, Gemini or Grok; the reply is this, and it is the only
#: shape here that carries confidence, sensitivity and a policy of its own.
PACK_FORMAT = "marvi-memory-pack/v1"

PACK_PROMPT = """Write out everything you know about me as a single JSON file I can import into
another assistant. Reply with ONLY the JSON, no commentary, in this format:

{
  "format": "marvi-memory-pack/v1",
  "subject": {"display_name": "...", "preferred_name": "...", "aliases": ["..."]},
  "entries": [
    {
      "kind": "fact | preference | goal | instruction",
      "category": "identity | work | health | projects | ... (your choice)",
      "text": "One complete sentence, third person, about me.",
      "stable": true,
      "sensitivity": "normal | personal | sensitive"
    }
  ]
}

Rules:
- One fact per entry. Write each as a full sentence that makes sense on its own.
- Include preferences about how I like to be talked to, my work, my projects,
  my hardware, and anything standing you have been told to do or avoid.
- NEVER include passwords, API keys, tokens, security answers, card or bank
  numbers, or national ID numbers. Leave them out entirely.
- Mark anything medical, financial or legal as "sensitive".
- Do not invent anything. If you are unsure, leave it out."""


def _from_pack(data: dict[str, Any]) -> list[str]:
    """Our own format, read properly because we defined it.

    Honours the pack's `never_import` policy in addition to the credential gate
    every source goes through, because a file that states its own rules should
    have them followed rather than merely be treated liberally.
    """
    banned = {
        str(word).strip().lower()
        for word in (data.get("import_policy") or {}).get("never_import", [])
        if str(word).strip()
    }
    found: list[str] = []
    for entry in data.get("entries") or []:
        if not isinstance(entry, dict):
            continue
        text = _clean(entry.get("text", ""))
        if not _usable(text):
            continue
        if any(word in text.lower() for word in banned):
            log.info("skipping an entry the pack's own policy excludes")
            continue
        # The category is carried in, the way a markdown heading is: "health"
        # over "smokes daily" is where that entry's meaning lives.
        category = _clean(entry.get("category", "")).replace("_", " ")
        found.append(f"{category}: {text}" if category else text)
    return found


def read(path: Path) -> list[str]:
    """Candidate memories in a file. Never raises; an unreadable file is empty."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        log.warning("could not read %s: %s", path, exc)
        return []
    stripped = text.lstrip()
    if stripped.startswith(("{", "[")):
        try:
            data = json.loads(text)
            if isinstance(data, dict) and str(data.get("format", "")).startswith(
                "marvi-memory-pack/"
            ):
                return _from_pack(data)[:MAX_ITEMS]
            return _from_json(data)[:MAX_ITEMS]
        except ValueError:
            # A .json that is not JSON is more likely a JSONL export than a
            # mistake, and reading it as text finds the lines anyway.
            log.info("%s is not valid JSON; reading it as text", path.name)
    return _from_markdown(text)[:MAX_ITEMS]


# -- providers with an API -----------------------------------------------------
#
# A file is the common case because most assistants cannot export. Honcho and
# Mem0 can, so for those the "file" is a network call and everything after it is
# the same pipeline.


#: Where an import looks for a key, in order.
#:
#: The memory *provider* setting holds one key for whichever provider is
#: selected, and importing from Honcho is not the same as switching to it: you
#: might pull your history out of Honcho precisely because you are leaving.
#: So the provider's key is used when it fits, and the provider's own
#: environment variable otherwise -- which is where it already is for anybody
#: who has used that assistant before.
def provider_key(provider: str) -> str:
    from . import memory_providers

    selected = memory_providers.describe().get("provider") == provider
    if selected and (key := os.environ.get(memory_providers.KEY_SETTING, "").strip()):
        return key
    return os.environ.get(f"{provider.upper()}_API_KEY", "").strip()


def provider_url(provider: str) -> str:
    from . import memory_providers

    configured = memory_providers.describe()
    if configured.get("provider") == provider:
        return str(configured.get("url") or "")
    return os.environ.get(f"{provider.upper()}_URL", "").strip()


def honcho_workspaces(api_key: str, url: str = "") -> list[str]:
    """Which workspaces this key can see.

    Asked rather than assumed: the default workspace on a real account was
    empty and everything was in one called `hermes`, so an importer that
    hardcoded `default` would have reported "nothing found" over a full
    account.
    """
    from honcho import Honcho

    client = Honcho(api_key=api_key or None, **({"base_url": url} if url else {}))
    return [str(getattr(row, "id", row)) for row in client.workspaces()]


def _peer_lines(peer: Any) -> list[str]:
    """One peer's card and representation, as sentences.

    Both, because they hold different things. The **card** is the derived,
    current summary -- `IDENTITY: Name: ...`, `ATTRIBUTE: Location: ...` -- and
    is the closest thing Honcho has to a durable profile. The
    **representation** is timestamped observations, which is where anything
    that happened lives.

    The peer's own id is stripped from the front of each observation. Honcho
    writes them as "<peer id> prefers X", and on a real account the peer ids
    were conversation titles -- so importing them verbatim produces memories
    that begin "user-default-Checking-Room-Light-Status prefers...".
    """
    pid = str(getattr(peer, "id", "") or "")
    found: list[str] = []

    try:
        card = peer.get_card() or []
    except Exception as exc:
        log.info("no card for %s: %s", pid, exc)
        card = []
    for entry in card:
        cleaned = _clean(str(entry))
        # `IDENTITY: Name: Shereef` reads better as `Name: Shereef`.
        cleaned = re.sub(r"^(IDENTITY|ATTRIBUTE|PREFERENCE|GOAL)\s*:\s*", "", cleaned, flags=re.I)
        if _usable(cleaned):
            found.append(cleaned)

    try:
        representation = peer.representation
        text = str(representation() if callable(representation) else representation or "")
    except Exception as exc:
        log.info("no representation for %s: %s", pid, exc)
        text = ""
    for raw in text.splitlines():
        line = _clean(raw)
        # `[2026-06-13 05:38:44] ` in front of every observation.
        line = re.sub(r"^\[\d{4}-\d{2}-\d{2}[^]]*\]\s*", "", line)
        if pid and line.lower().startswith(pid.lower()):
            line = line[len(pid) :].lstrip("'s ").strip()
            line = f"The user {line}" if line else ""
        if _usable(line):
            found.append(line)
    return found


def from_honcho(api_key: str, workspace: str, url: str = "") -> list[str]:
    """Every peer's card and observations in one workspace.

    Never raises: an import that cannot reach the network is an import that
    found nothing, which the caller already knows how to report.
    """
    try:
        from honcho import Honcho

        client = Honcho(
            api_key=api_key or None,
            workspace_id=workspace,
            **({"base_url": url} if url else {}),
        )
        found: list[str] = []
        for peer in client.peers():
            found.extend(_peer_lines(peer))
        # One assistant talking to itself writes the same observation into
        # several peers; a real account had eight peers each holding the same
        # sentence. Order is kept because the first occurrence is the oldest.
        return list(dict.fromkeys(found))[:MAX_ITEMS]
    except Exception as exc:
        log.warning("could not read Honcho: %s", exc)
        return []


def from_mem0(api_key: str, user_id: str, url: str = "") -> list[str]:
    """Everything Mem0 holds for this user.

    Through the REST API rather than the SDK: the SDK's shape has moved between
    versions and this needs one endpoint. `v1/memories?user_id=` is the listing
    both the managed platform and the self-hosted OSS server serve.
    """
    import httpx

    base = (url or "https://api.mem0.ai").rstrip("/")
    try:
        response = httpx.get(
            f"{base}/v1/memories/",
            params={"user_id": user_id},
            headers={"Authorization": f"Token {api_key}"} if api_key else {},
            timeout=30.0,
        )
        response.raise_for_status()
        return _from_json(response.json())[:MAX_ITEMS]
    except Exception as exc:
        log.warning("could not read Mem0: %s", exc)
        return []


def _parse(text: str) -> list[dict[str, Any]]:
    body = (text or "").strip().strip("`")
    if body.lower().startswith("json"):
        body = body[4:].strip()
    start, end = body.find("{"), body.rfind("}")
    if start < 0 or end <= start:
        return []
    try:
        parsed = json.loads(body[start : end + 1])
    except ValueError:
        return []
    found = parsed.get("memories") if isinstance(parsed, dict) else None
    return [row for row in (found or []) if isinstance(row, dict)]


def organise(client: Any, lines: list[str], known: list[str]) -> list[dict[str, str]]:
    """Turn somebody else's memories into Marvi's, in batches.

    Returns `[]` when there is no model, which is not the same as an empty
    import: the caller says so, because silently storing the raw lines would
    put another assistant's formatting into this one's prompt forever.
    """
    if client is None or not lines:
        return []
    already = "\n".join(f"- {row}" for row in known[:80]) or "(nothing yet)"
    organised: list[dict[str, str]] = []
    for start in range(0, len(lines), BATCH):
        batch = lines[start : start + BATCH]
        try:
            answer = distil.ask(
                client,
                "memory",
                SYSTEM_PROMPT,
                "ALREADY KNOWN:\n"
                + already
                + "\n\nTO IMPORT:\n"
                + "\n".join(f"- {row}" for row in batch),
                MAX_OUTPUT_TOKENS,
                tools=False,
            )
        except Exception as exc:
            log.warning("could not organise a batch of %d: %s", len(batch), exc)
            continue
        for row in _parse(answer):
            subject = str(row.get("subject") or "").strip()[:200]
            body = str(row.get("body") or "").strip()[:MAX_LENGTH]
            if not subject or not body:
                continue
            kind = "episodic" if str(row.get("kind") or "").strip() == "episodic" else "semantic"
            organised.append({"subject": subject, "body": body, "kind": kind})
    return organised


def preview(
    paths: list[Path], *, lines: list[str] | None = None, name: str = ""
) -> dict[str, Any]:
    """What is there, before anything is written.

    Reports what the credential gate would refuse as well as what it would
    keep. Somebody importing years of an assistant's notes should be told that
    thirteen of them were passwords before it happens, not after.
    """
    if lines is not None:
        per_file = {name or "provider": list(lines)}
    else:
        per_file = {path.name: read(path) for path in paths}
    lines = [line for found in per_file.values() for line in found]
    refused = [{"reason": why, "quote": line[:160]} for line in lines if (why := unsafe(line))]
    return {
        "files": [{"name": file, "found": len(found)} for file, found in per_file.items()],
        "found": len(lines),
        "refused": refused,
        # A handful, so somebody can tell a memory file from a config file they
        # picked by mistake before it is imported.
        "sample": [line for line in lines if not unsafe(line)][:8],
    }


def run(
    store: Any,
    client: Any,
    paths: list[Path],
    *,
    lines: list[str] | None = None,
    source: str = "",
) -> dict[str, Any]:
    """Read, organise, store, and dream over what arrived.

    The dream at the end is not decoration: an imported set is a pile of
    statements with relations between them that nobody has drawn, which is
    exactly the case dreaming exists for -- and it is why the graph fills the
    moment somebody imports two years of notes rather than waiting for two
    years of conversation.
    """
    # `lines` is what a provider read over the network. Files and APIs differ
    # only in where the sentences came from; everything after this point is one
    # pipeline, which is the whole reason it is shaped this way.
    candidates = (
        list(lines) if lines is not None else [line for path in paths for line in read(path)]
    )[:MAX_ITEMS]
    lines, refused = [], []
    for line in candidates:
        reason = unsafe(line)
        if reason:
            refused.append({"reason": reason, "quote": line[:160]})
        else:
            lines.append(line)
    if refused:
        log.warning(
            "refused %d imported line(s) that read as instructions rather than facts",
            len(refused),
        )
    if not lines:
        return {
            "found": len(candidates),
            "imported": 0,
            "refused": refused,
            "detail": "nothing in those files looked like a memory",
        }

    known = [f"{row['subject']}: {row['body']}" for row in store.recent(limit=80)]
    organised = organise(client, lines, known)
    if not organised:
        return {
            "found": len(lines),
            "imported": 0,
            "refused": refused,
            "detail": "no model is available to organise the import, and storing another "
            "assistant's notes unchanged would put its formatting into this one",
        }

    # Marked as an import, not inferred later from what the source looks like.
    # See `MemoryStore.IMPORTED`.
    named = (source or ", ".join(path.name for path in paths))[:100]
    source = f"{store.IMPORTED}{named}"
    stored = 0
    for row in organised:
        try:
            # Untrusted: Marvi did not hear this and cannot vouch for it. The
            # envelope on recall is the same one an email gets, which is right
            # -- it came from outside.
            store.remember_external(row["subject"], row["body"], source=source, kind=row["kind"])
            stored += 1
        except Exception as exc:
            log.warning("could not store an imported memory: %s", exc)

    if stored:
        store.forget_imported_sources()
    log.info(
        "memories imported",
        extra={"marvi_found": len(lines), "marvi_stored": stored, "marvi_source": source},
    )
    return {
        "found": len(lines),
        "imported": stored,
        "refused": refused,
        "detail": "",
        "source": named,
    }
