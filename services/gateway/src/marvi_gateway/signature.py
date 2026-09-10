"""Which Gateway this is, and whether it is the one you meant to talk to.

The desktop finds something already listening on 8765 and has to decide: use
it, or replace it. Every way of deciding that has been wrong at least once.

**By whether the port is open.** So the desktop attached to whatever answered,
which one night was another install's Gateway, with another install's settings
and another install's tools. Marvi simply behaved like a different Marvi and
nothing said why.

**By whether the process is alive.** An abandoned Gateway gets killed and a
live one is spared -- correct as far as it goes, and it still leaves the worst
case: a *live* Gateway that is not yours. A second checkout, or the one an
agent left running after a test in the repo.

**By version number.** Which is the trap this module exists for. A version
changes on release; a nightly's code changes every hour. Two Gateways built
four hours apart from the same branch report the same version, so the check
passes and the older one keeps serving -- with whatever bug was fixed in
between, silently, for as long as it stays up. A check that only fails on
release day is not a check.

So: a signature over the code actually loaded. Same bytes, same answer;
one file different, different answer. It is not a security measure -- anything
on this machine could produce one -- it is an identity, in the way an ETag is
an identity. The question it answers is "is that Gateway the same build as
me", and nothing else answers it.

## What it covers

The Python sources of the Gateway package, by content. Not the install
directory's mtimes, which change on copy; not the git commit, which is absent
in a packaged build and identical across a dirty tree.
"""

from __future__ import annotations

import hashlib
import os
from functools import lru_cache
from pathlib import Path

#: How much of the digest to show. Twelve hex characters is 48 bits -- far
#: past coincidence for the handful of builds that ever exist at once, and
#: short enough to read in a log line next to a PID.
SHOWN = 12

#: Set by a test or a packaged build that knows its own identity.
SETTING = "MARVI_BUILD_SIGNATURE"


def _sources(root: Path) -> list[Path]:
    """Every Python file in the package, in a stable order.

    Sorted by relative path so two checkouts at different absolute paths
    produce the same signature -- otherwise `D:\\Marvi-OS` and the install
    copy of identical code would look like different builds, which is the
    false positive that would make this useless.
    """
    return sorted((p for p in root.rglob("*.py") if "__pycache__" not in p.parts),
                  key=lambda p: p.relative_to(root).as_posix())


@lru_cache(maxsize=1)
def build() -> str:
    """This Gateway's build signature. Stable for the life of the process.

    Cached deliberately: it describes the code *loaded*, which cannot change
    while running. Re-reading it would let a Gateway report a build it is not
    executing, which is worse than not reporting one.
    """
    if said := os.environ.get(SETTING, "").strip():
        return said[:SHOWN]
    root = Path(__file__).resolve().parent
    digest = hashlib.sha256()
    for path in _sources(root):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        try:
            digest.update(path.read_bytes())
        except OSError:  # pragma: no cover - a file vanishing mid-scan
            digest.update(b"?")
    return digest.hexdigest()[:SHOWN]


def mine(other: str) -> bool:
    """Whether a signature from elsewhere is this same build."""
    return bool(other) and other.strip().lower() == build()


def describe() -> dict[str, object]:
    """What `/health` publishes so a caller can decide to attach or replace."""
    return {"build": build(), "pid": os.getpid()}
