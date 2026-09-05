"""Async code must not call a helper that makes a blocking network call.

The direct shape of this -- `httpx.post` written inside an `async def` -- is
easy to see and was never the problem. The one that cost a turn was one call
deeper:

    @session.on("user_input_transcribed")
    def _heard_live(event):
        _report_transcript(heard=text)     # blocking httpx.post, 1.5s timeout

`user_input_transcribed` fires on every interim result, so that ran on the
agent's event loop -- the one carrying the audio -- 56 times across five turns
of one real session. Three such reports can precede a reply, at 1.5s each, so
a Gateway that was slow to answer made the *turn* slow. That is the mechanism
behind the slow first turn: during an eleven-second embedding load they timed
out one after another.

Static rather than a runtime assertion because the failure is silent and only
shows up as latency, which is exactly the kind of thing nobody bisects.
"""

from __future__ import annotations

import ast
import pathlib

#: What counts as blocking. Network calls and sleeps; not disk, which is fast
#: enough locally that flagging it would bury the signal in config reads.
BLOCKING = (
    "httpx.get", "httpx.post", "httpx.put", "httpx.delete", "httpx.request",
    "requests.", "time.sleep", "subprocess.run", "subprocess.check_output", "urlopen",
)

#: Ways of handing the work somewhere else that make it fine again.
HANDED_OFF = ("to_thread", "run_in_executor", "_in_background", "Thread(", "ThreadPoolExecutor")

#: Known, deliberate, and each one argued rather than merely tolerated.
#:
#: An allowlist is where a check like this rots, so every entry names the
#: reason and none of them is "it was already like that".
ALLOWED = {
    # The recall whose result goes *into* the turn, so the turn does have to
    # wait for it -- and it is the fallback path, taken only when the prefetch
    # missed. Measured over a real session: the prefetch hit 5 of 5.
    #
    # Deliberately not moved to `asyncio.to_thread`. Awaiting would yield the
    # loop in the middle of `on_user_turn_completed`, and LiveKit's preemptive
    # generation is speculating against this exact context at this exact
    # moment. Making those two coexist was hard-won and is not worth
    # re-litigating for a path that does not run.
    ("session.py", "on_user_turn_completed", "_recall"),
    # Shutdown, not a turn: it runs after `live.stop()` has already released
    # the process the next call will use, so nothing is waiting on it.
    ("session.py", "marvi_session", "_remember_the_session"),
}

ROOTS = (
    pathlib.Path(__file__).parents[3] / "agent" / "src",
    pathlib.Path(__file__).parents[3] / "gateway" / "src",
)


def _name(node: ast.AST) -> str:
    bits = []
    while isinstance(node, ast.Attribute):
        bits.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        bits.append(node.id)
    return ".".join(reversed(bits))


def _blocking_helpers(tree: ast.AST, lines: list[str]) -> dict[str, int]:
    """Plain functions whose body blocks and does not hand the work off."""
    found = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef):
            body = "\n".join(lines[node.lineno - 1 : node.end_lineno])
            if any(b in body for b in BLOCKING) and not any(h in body for h in HANDED_OFF):
                found[node.name] = node.lineno
    return found


def test_no_async_function_waits_on_the_network() -> None:
    offences = []
    for root in ROOTS:
        for path in root.rglob("*.py"):
            if ".venv" in path.parts:
                continue
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text)
            helpers = _blocking_helpers(tree, text.splitlines())
            if not helpers:
                continue
            for node in ast.walk(tree):
                if not isinstance(node, ast.AsyncFunctionDef):
                    continue
                for inner in ast.walk(node):
                    if not isinstance(inner, ast.Call):
                        continue
                    called = _name(inner.func).split(".")[-1]
                    if called not in helpers:
                        continue
                    if (path.name, node.name, called) in ALLOWED:
                        continue
                    offences.append(
                        f"{path.name}:{inner.lineno} async {node.name}() calls "
                        f"{called}(), which blocks (defined line {helpers[called]})"
                    )

    assert not offences, (
        "these run a network call on the event loop; hand them to a thread "
        "(see `_in_background`) or add an argued entry to ALLOWED:\n  "
        + "\n  ".join(offences)
    )


def test_the_allowlist_still_describes_real_code() -> None:
    """An allowlist that names something that no longer exists is a lie.

    Without this the entries outlive the code they excuse, and the next person
    reads two confident paragraphs about a call that was deleted a year ago.
    """
    for filename, caller, callee in ALLOWED:
        matches = [path for root in ROOTS for path in root.rglob(filename)]
        assert matches, f"{filename} is on the allowlist and does not exist"
        text = matches[0].read_text(encoding="utf-8")
        assert f"def {caller}" in text, f"{caller}() is gone; drop it from ALLOWED"
        assert f"def {callee}" in text, f"{callee}() is gone; drop it from ALLOWED"
