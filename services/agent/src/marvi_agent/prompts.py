"""The Agent's reader for the same `prompts/` directory the Gateway uses.

Two processes, two packages, one set of files. The Agent cannot import
`marvi_gateway`, and copying the text would put it back where it started --
`deliberate.SYSTEM_PROMPT` contradicted the persona files for months precisely
because the same rule existed in two places nobody compared.

Deliberately smaller than the Gateway's `prompts.py`: the Agent only reads, and
only prompts that take no variables. Anything needing composition comes over
`/context`, which the Gateway already builds.
"""

from __future__ import annotations

import os
import re
from functools import cache, lru_cache
from pathlib import Path

#: Same frontmatter shape as the Gateway's loader and Claude Code's files.
FRONT = re.compile(r"\A<!--\n.*?\n-->\n?", re.S)

#: Where to look when the repository layout is not underfoot -- an install puts
#: the services somewhere else entirely.
SETTING = "MARVI_PROMPTS_DIR"


@lru_cache(maxsize=1)
def folder() -> Path:
    if said := os.environ.get(SETTING, "").strip():
        return Path(said)
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "prompts").is_dir():
            return parent / "prompts"
    return here.parent / "prompts"


#: The one thing a body interpolates. Everything else is prose -- the same rule
#: as the Gateway's loader, and for the same reason: `string.Template` reads
#: `$$` as an escaped dollar and would eat a LaTeX delimiter.
SLOT = re.compile(r"\$\{(?P<name>[A-Za-z_][A-Za-z0-9_]*)\}")


@cache
def body(key: str) -> str:
    """One prompt's raw body, or empty when it is not there.

    Empty rather than raising: a missing prompt file should cost Marvi one
    paragraph of instruction, not her voice. The caller decides whether that
    matters, and `session.py` keeps a short fallback for the two that do.
    """
    try:
        raw = (folder() / f"{key}.md").read_text(encoding="utf-8")
    except OSError:
        return ""
    return FRONT.sub("", raw).strip()


def text(key: str, **values: object) -> str:
    """The prompt with its slots filled.

    An unfilled slot is left as written rather than raising. The Gateway's
    loader is strict because a missing value there is a bug in the Gateway;
    here the same thing means the prompts directory and this code have drifted
    apart, and going silent mid-conversation is worse than one visible slot.
    """
    said = body(key)
    if not said or not values:
        return said
    return SLOT.sub(lambda hit: str(values.get(hit["name"], hit[0])), said)
