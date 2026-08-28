"""The words the recogniser has no way to know.

Measured against both recognisers on this machine, saying the same five
sentences through Marvi's own voice:

    said        v3 multilingual     v2 English-only
    NeuDocs     "new docs"          "new docs"
    Marvi       "Marvey"            "Marvy"
    Shereef     "Sheriff"           "Sherif"
    Düzce       "DUS"               "Doz"

Every ordinary English word came back right in both. Every failure was a proper
noun. That is not a model-quality problem and no bigger model fixes it: these
words are not in either vocabulary, and Parakeet through `onnx-asr` has no
contextual-biasing hook to put them there.

What Marvi does have is a list of exactly these words. The dreamer names the
entities in her graph -- Marvi, NeuDocs, Düzce, Shereef, xRetro, Kokoro -- and
those are precisely the words a general recogniser cannot spell and that matter
most when it fails, because they are what the sentence is *about*.

So the correction happens after recognition, against a vocabulary the
assistant already holds. It is the cheap end of contextual biasing: not as good
as biasing the decoder, and available, which the decoder hook is not.
"""

from __future__ import annotations

import re
from typing import Any

from .logs import get_logger

log = get_logger("gateway")

#: Below this a name is too short to correct safely. "Ana" would swallow "an
#: a", and a two-letter entity matches half the language.
MIN_LENGTH = 4

#: How many names the agent is given. The graph is small and the prompt is not
#: involved, but a recogniser correction that scans a thousand names per
#: utterance is a cost on a path that has none to spare.
MAX_TERMS = 120


def _usable(name: str) -> bool:
    cleaned = name.strip()
    if len(cleaned) < MIN_LENGTH or len(cleaned) > 40:
        return False
    # Paths, URLs and identifiers are not things anybody says out loud.
    return not re.search(r"[\\/@:]|\.\w{2,4}$", cleaned)


def terms(memory: Any = None, identity: Any = None) -> list[str]:
    """Proper nouns worth correcting a transcript against, most connected first.

    Ordered by how many relations an entity has, because the things Marvi knows
    most about are the things her user talks about most -- and if the list has
    to be cut, that is the right end to cut.
    """
    found: list[str] = []
    seen: set[str] = set()

    def keep(name: str) -> None:
        cleaned = " ".join(str(name).split())
        if _usable(cleaned) and cleaned.lower() not in seen:
            seen.add(cleaned.lower())
            found.append(cleaned)

    # Her own name first: it is the one word every sentence to her may contain,
    # and the one the log showed mangled most -- Morvey, Marvey, Marvy.
    keep("Marvi")

    if memory is not None:
        try:
            rows = memory._db.execute(
                "SELECT e.name, COUNT(r.id) AS links FROM entities e"
                " LEFT JOIN relations r"
                "   ON r.subject_id = e.id OR r.object_id = e.id"
                " GROUP BY e.id ORDER BY links DESC"
            ).fetchall()
            for row in rows:
                keep(str(row["name"]))
        except Exception as exc:  # pragma: no cover - depends on the store
            log.warning("could not read the graph for the recogniser: %s", exc)

    if identity is not None:
        # Names the user wrote down themselves carry more weight than anything
        # derived, so they are worth having even though they arrive last.
        try:
            for line in str(identity.read("USER.md") or "").splitlines():
                for word in re.findall(r"\b[A-Z][A-Za-z0-9-]{3,}\b", line):
                    keep(word)
        except Exception:  # pragma: no cover - depends on the file
            pass

    return found[:MAX_TERMS]
