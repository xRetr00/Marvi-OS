"""Score Marvi against what she actually did, not against scripted cases.

The other suites here send made-up turns to a model and check the reply. They
are useful and they are all frozen at the moment somebody wrote them: every
case in `docs/evals/` was found by reading a log by hand, which means the next
bug is found the same way or not at all.

This reads `observations.jsonl` -- the rows Marvi writes as she runs -- and
reports the same failures against real use. Nothing here invents a case. If it
says a prompt leaked, a prompt leaked, in a conversation that happened.

    python evals/from_life.py                # everything, last 1000 rows
    python evals/from_life.py --days 3       # only recent
    python evals/from_life.py --kind tool    # one section

## What it looks for, and why each one is here

**Replies** -- prompt leaks, monologues and tool narration. All three were
found by hand in a single session, all three are one substring test, and none
of them was being watched.

**Recall** -- how often the search came back weak, and how often the reader had
to say it did not know. A rising weak rate is the store drifting away from the
questions being asked; it is invisible from inside a conversation.

**Storing** -- how many turns produced a memory. The memory worker ran for
weeks keeping 17 of every 25 facts it should have, and nothing said so, because
an extraction that returns nothing looks exactly like a turn with nothing in it.

**Tools** -- what is called, what fails, what is slow, and the row that matters
most: searches that found nothing. That is the only honest signal about which
tools Marvi is missing.

**Gates** -- how much a connector offered and how much was kept. A gate keeping
everything is a gate that is not working; a gate keeping nothing is worse.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import pathlib
import statistics
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # type: ignore[union-attr]
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "services/gateway/src"))

#: Phrases that only appear when a model is continuing its context rather than
#: answering from it. Every one was spoken aloud by Marvi in a real session.
LEAKED = (
    "prefer what the user",
    "answer as yourself",
    "do not repeat them back",
    "names marvi",
    "do not restate",
    "no need to announce",
    "what you remember is only",
    "never say that you are about to",
)

NARRATION = (
    "let me check",
    "let me look",
    "let me see",
    "i'll check",
    "i will check",
    "let me find",
    "i'm going to use",
)

#: Roughly twenty seconds of speech. Past this it stops being a spoken answer;
#: one real reply ran 67.8 seconds.
LONG_WORDS = 60


def load(days: float | None) -> list[dict]:
    from marvi_gateway import observations

    rows = observations.read(limit=observations.MAX_ROWS)
    if days:
        cutoff = time.time() - days * 86_400
        rows = [row for row in rows if float(row.get("at") or 0) >= cutoff]
    return rows


def replies(rows: list[dict]) -> None:
    said = [row for row in rows if row.get("kind") == "reply"]
    if not said:
        print("  no spoken turns recorded yet")
        return
    leaks, narrated, longest = [], [], []
    for row in said:
        text = str(row.get("said") or "").lower()
        if any(phrase in text for phrase in LEAKED):
            leaks.append(row)
        if any(phrase in text for phrase in NARRATION):
            narrated.append(row)
        if len(text.split()) > LONG_WORDS:
            longest.append(row)
    print(f"  {len(said)} spoken turns")
    print(f"    prompt leaked      {len(leaks):>4}   ({100 * len(leaks) / len(said):.1f}%)")
    print(f"    narrated a tool    {len(narrated):>4}   ({100 * len(narrated) / len(said):.1f}%)")
    print(f"    over {LONG_WORDS} words       {len(longest):>4}   "
          f"({100 * len(longest) / len(said):.1f}%)")
    for row in (leaks + narrated + longest)[:3]:
        print(f"      e.g. {json.dumps(str(row.get('said'))[:110])}")


def recalls(rows: list[dict]) -> None:
    found = [row for row in rows if row.get("kind") == "recall"]
    if not found:
        print("  no recalls recorded yet")
        return
    weak = [row for row in found if row.get("weak")]
    empty = [row for row in found if not row.get("found")]
    best = [float(row.get("best") or 0) for row in found if row.get("best")]
    print(f"  {len(found)} recalls")
    print(f"    nothing found      {len(empty):>4}   ({100 * len(empty) / len(found):.1f}%)")
    print(f"    weak match         {len(weak):>4}   ({100 * len(weak) / len(found):.1f}%)")
    if best:
        print(f"    best score         median {statistics.median(best):.3f}")
    for row in weak[:3]:
        print(f"      weak on: {json.dumps(str(row.get('question'))[:80])}")


def stores(rows: list[dict]) -> None:
    kept = [row for row in rows if row.get("kind") == "store"]
    if not kept:
        print("  no turns judged yet")
        return
    wrote = [row for row in kept if (row.get("add") or 0) or (row.get("update") or 0)]
    print(f"  {len(kept)} turns judged, {len(wrote)} produced a memory "
          f"({100 * len(wrote) / len(kept):.1f}%)")
    # Not a target. Most turns genuinely hold nothing, and a rate near 100%
    # would mean the worker had stopped discriminating. It is here because a
    # rate of *zero* over a day is the failure that hid for weeks.
    if not wrote:
        print("    nothing stored at all -- check the extractor before trusting this")


def tools(rows: list[dict]) -> None:
    calls = [row for row in rows if row.get("kind") == "tool" and row.get("event") == "call"]
    searches = [row for row in rows if row.get("kind") == "tool" and row.get("event") == "search"]
    if calls:
        by_name = collections.Counter(str(row.get("name")) for row in calls)
        failed = [row for row in calls if row.get("failed")]
        slow = sorted(calls, key=lambda row: -float(row.get("ms") or 0))[:3]
        print(f"  {len(calls)} tool calls, {len(failed)} failed")
        print(f"    most used: {', '.join(f'{n} x{c}' for n, c in by_name.most_common(5))}")
        for row in slow:
            print(f"    slowest: {row.get('name')} {row.get('ms')}ms")
        for row in failed[:3]:
            print(f"    failed: {row.get('name')} -- {str(row.get('failed'))[:70]}")
    if searches:
        missed = [row for row in searches if not row.get("found")]
        print(f"  {len(searches)} tool searches, {len(missed)} found nothing")
        # The reason this suite exists. A search that finds nothing is Marvi
        # reaching for a capability she does not have, and it is the only
        # honest answer to "which tools should we add".
        for query, count in collections.Counter(
            str(row.get("query")) for row in missed
        ).most_common(8):
            print(f"    wanted and missing: {query!r} x{count}")


def gates(rows: list[dict]) -> None:
    ingest = [row for row in rows if row.get("kind") == "gate" and row.get("door") == "ingest"]
    proposed = [row for row in rows if row.get("kind") == "gate" and row.get("door") == "tool"]
    if ingest:
        offered = sum(int(row.get("offered") or 0) for row in ingest)
        kept = sum(int(row.get("kept") or 0) for row in ingest)
        print(f"  connectors offered {offered}, kept {kept}")
        if offered and kept == offered:
            print("    kept everything -- the gate may not be running")
        if offered and kept == 0:
            print("    kept nothing -- check before trusting this")
    if proposed:
        kept = [row for row in proposed if row.get("kept")]
        print(f"  conversation proposed {len(proposed)} memories, kept {len(kept)}")
        for row in [r for r in proposed if not r.get("kept")][:3]:
            print(f"    refused: {json.dumps(str(row.get('body'))[:70])}")


SECTIONS = {
    "reply": ("What she said", replies),
    "recall": ("What memory answered", recalls),
    "store": ("What memory kept", stores),
    "tool": ("Tools", tools),
    "gate": ("Gates", gates),
}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=float, default=None, help="only the last N days")
    parser.add_argument("--kind", choices=sorted(SECTIONS), help="one section only")
    args = parser.parse_args()

    from marvi_gateway.providers import config as provider_config

    for name, value in provider_config.read().items():
        os.environ.setdefault(name, value)

    rows = load(args.days)
    if not rows:
        print(
            "Nothing recorded yet. Observations are written as Marvi runs "
            "(see `observations.py`); use her for a while and run this again."
        )
        return
    span = (time.time() - float(rows[0].get("at") or time.time())) / 86_400
    print(f"{len(rows)} observations over {span:.1f} days\n")
    for key, (title, section) in SECTIONS.items():
        if args.kind and args.kind != key:
            continue
        print(f"== {title} ==")
        section(rows)
        print()


if __name__ == "__main__":
    main()
