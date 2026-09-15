"""Cortex as an Obsidian vault: one note per subject, relations as [[links]].

`/memory/export` already hands the user their memories as JSON, which is the
right shape for a backup and the wrong one for reading. Obsidian's graph view
is the same picture the Cortex page draws, and a folder of Markdown outlives
any app. OpenHuman mirrors its memory the same way (GPL-3.0, idea only).

One-way and read-only: the memory database is opened `mode=ro`, so exporting
while the Gateway runs cannot disturb it, and editing a note does not edit a
memory. Re-exporting overwrites the notes this wrote and nothing else.

    marvi memory export --obsidian D:\\Notes\\Marvi
"""

from __future__ import annotations

import re
import sqlite3
from collections import defaultdict
from pathlib import Path
from typing import Any

INDEX_NOTE = "Marvi Cortex"
_UNSAFE = re.compile(r'[\\/:*?"<>|#^\[\]]+')


def _note_names(names: list[str]) -> dict[str, str]:
    """A filename per subject, unique even on a case-insensitive disk."""
    chosen: dict[str, str] = {}
    taken: set[str] = {INDEX_NOTE.lower()}
    for name in names:
        base = _UNSAFE.sub("-", name).strip(" .-")[:100] or "untitled"
        candidate, n = base, 2
        while candidate.lower() in taken:
            candidate, n = f"{base} ({n})", n + 1
        taken.add(candidate.lower())
        chosen[name] = candidate
    return chosen


def read(db_path: Path) -> tuple[list[dict[str, Any]], list[tuple[str, str, str]]]:
    """Memories and (subject, predicate, object) relations, read-only."""
    db = sqlite3.connect(f"file:{db_path.as_posix()}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    try:
        memories = [dict(r) for r in db.execute(
            "SELECT id, kind, subject, body, source, trusted, at FROM memories ORDER BY id"
        )]
        relations = [(r[0], r[1], r[2]) for r in db.execute(
            "SELECT s.name, r.predicate, o.name FROM relations r "
            "JOIN entities s ON s.id = r.subject_id JOIN entities o ON o.id = r.object_id "
            "ORDER BY s.name, r.predicate, o.name"
        )]
    finally:
        db.close()
    return memories, relations


def export(db_path: Path, target: Path) -> dict[str, int]:
    memories, relations = read(db_path)
    by_subject: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for memory in memories:
        by_subject[str(memory["subject"]).strip() or "untitled"].append(memory)
    links: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for subject, predicate, obj in relations:
        links[subject].append((predicate, obj))

    subjects = sorted(set(by_subject) | set(links) | {o for _, _, o in relations}, key=str.lower)
    names = _note_names(subjects)
    target.mkdir(parents=True, exist_ok=True)

    for subject in subjects:
        rows = by_subject.get(subject, [])
        lines = [
            "---",
            "source: marvi-cortex",
            f"memories: {len(rows)}",
            "---",
            f"# {subject}",
            "",
        ]
        for memory in rows:
            untrusted = "" if memory["trusted"] else ", untrusted"
            lines.append(f"- {memory['body']}  _({memory['kind']}, {memory['source']}{untrusted}, {memory['at'][:10]})_")
        if links.get(subject):
            lines += ["", "## Links", ""]
            lines += [f"- {predicate} [[{names[obj]}]]" for predicate, obj in links[subject]]
        (target / f"{names[subject]}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

    index = [f"# {INDEX_NOTE}", "", f"{len(memories)} memories, {len(relations)} links.", ""]
    index += [f"- [[{names[s]}]]" for s in subjects]
    (target / f"{INDEX_NOTE}.md").write_text("\n".join(index) + "\n", encoding="utf-8")
    return {"notes": len(subjects) + 1, "memories": len(memories), "links": len(relations)}
