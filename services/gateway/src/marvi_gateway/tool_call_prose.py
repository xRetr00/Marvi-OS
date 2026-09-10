"""A tool call the model typed out instead of making.

Every provider has its own markup for calling a tool, and the runtime parses
it out before the text reaches anybody. Sometimes it does not: the model emits
the markup slightly wrong, or in a place the parser is not looking, and the
whole thing arrives as the assistant's reply. In the chat window that looked
like this, verbatim, as her entire answer:

    <tool_call>terminal_run <arg_key>command</arg_key> <arg_value>Get-Process
    -Name "Sidecar" -ErrorAction SilentlyContinue; ...</arg_value>
    <arg_key>shell</arg_key> <arg_value>powershell</arg_value> </tool_call>

Which tells the user nothing except that something is broken, and does not
tell them *what*. The tool never ran, so whatever she was about to say next
was never going to arrive either.

Two things follow from that, and they are different:

* **Never show it.** It is machinery, and showing machinery to somebody who
  asked a question is worse than saying nothing.
* **Say the call did not happen.** Silently dropping the markup would leave a
  blank reply, which reads as Marvi having nothing to say when in fact she
  tried to do something and the plumbing lost it.

Written to the *shape* rather than to any vendor. The voice side has its own
narrower pattern for DeepSeek's `<|DSML|...>` form; this covers the angle-
bracket family that DeepSeek's does not, and both exist because a model that
does this once does it in whichever dialect it was trained on.
"""

from __future__ import annotations

import re

#: The opening of a tool call written as text.
#:
#: `<tool_call>`, `<function_call>`, `<invoke name="...">`, `<|DSML|...>` and
#: the closing forms of each. Deliberately anchored on names that do not occur
#: in prose -- `<b>` and `<br>` must survive, because a reply may legitimately
#: contain a little markup and eating it would be its own bug.
MARKUP = re.compile(
    r"</?\s*(?:\|[^>]{0,120}\||tool_call|tool_calls|function_call|invoke|"
    r"arg_key|arg_value|parameter|antml:[a-z_]+)[^>]{0,200}>",
    re.I,
)

#: The tool being reached for, when the markup names one.
NAMED = re.compile(
    r"<\s*(?:tool_call|function_call|invoke)[^>]{0,80}>\s*([a-z][a-z0-9_]{2,60})|"
    r'name\s*=\s*["\']([a-z][a-z0-9_]{2,60})["\']',
    re.I,
)

#: How much markup makes a reply *about* markup rather than one containing it.
#:
#: A reply explaining tool syntax to somebody -- "you write `<tool_call>` and
#: then the name" -- is a real answer and must not be swallowed. The signal
#: that separates them is that a mis-emitted call is almost entirely markup,
#: so this compares what is left after removing it.
MOSTLY = 0.5


def looks_typed_out(text: str) -> bool:
    """Whether this reply is a tool call the model wrote instead of made."""
    if not text or "<" not in text:
        return False
    found = MARKUP.findall(text)
    if len(found) < 2:
        # One tag is a stray bracket or a sentence about markup. A real
        # mis-emitted call always carries at least an opening and something
        # else -- a close, an argument key, a name.
        return False
    without = MARKUP.sub("", text)
    return len(without.strip()) < len(text.strip()) * MOSTLY


def reached_for(text: str) -> str:
    """The tool it was trying to call, or empty when the markup does not say."""
    found = NAMED.search(text or "")
    if not found:
        return ""
    return (found.group(1) or found.group(2) or "").strip()


#: `<arg_key>name</arg_key> <arg_value>value</arg_value>`, the paired form.
PAIRED = re.compile(
    r"<\s*arg_key\s*>(?P<key>.*?)</\s*arg_key\s*>\s*"
    r"<\s*arg_value\s*>(?P<value>.*?)</\s*arg_value\s*>",
    re.I | re.S,
)

#: `<parameter name="k">v</parameter>`, the other common shape.
NAMED_PARAM = re.compile(
    r"<\s*parameter\s+name\s*=\s*[\"'](?P<key>[^\"']+)[\"'][^>]*>"
    r"(?P<value>.*?)</\s*parameter\s*>",
    re.I | re.S,
)


def _typed(value: str) -> object:
    """A value the model wrote as text, as the thing it meant.

    Everything arrives as a string here because the markup has no types. A
    tool declaring `lines: int` would refuse `"40"` -- the same disagreement
    `_coerce` exists for -- so the obvious literals are read back.
    """
    said = value.strip()
    if said.lower() in ("true", "false"):
        return said.lower() == "true"
    if re.fullmatch(r"-?\d+", said):
        return int(said)
    if re.fullmatch(r"-?\d*\.\d+", said):
        return float(said)
    if said[:1] in "{[":
        import json

        try:
            return json.loads(said)
        except ValueError:
            return said
    return said


def recover(text: str) -> dict[str, object] | None:
    """The call the model meant, as a call. None when it cannot be read.

    This is the part that makes the difference between an error and a working
    turn. Stripping the markup and apologising is honest but wasteful: the
    model said exactly which tool it wanted and with what, and every bit of
    that survives in the text. Reading it back means the tool actually runs
    and the conversation continues, instead of ending in an apology for
    something that was recoverable.

    Deliberately conservative. A name that is not a plausible tool name, or
    arguments that cannot be read at all, returns None -- and the caller hands
    the failure to the model rather than guessing.
    """
    if not looks_typed_out(text):
        return None
    name = reached_for(text)
    if not name:
        # A JSON body is the other common shape:
        # `<tool_call>{"name": "x", "arguments": {...}}</tool_call>`
        import json

        body = MARKUP.sub(" ", text).strip()
        try:
            parsed = json.loads(body)
        except ValueError:
            return None
        if not isinstance(parsed, dict) or not parsed.get("name"):
            return None
        arguments = parsed.get("arguments") or parsed.get("parameters") or {}
        return {
            "name": str(parsed["name"]),
            "arguments": arguments if isinstance(arguments, dict) else {},
        }
    arguments: dict[str, object] = {}
    for pattern in (PAIRED, NAMED_PARAM):
        for hit in pattern.finditer(text):
            arguments[hit["key"].strip()] = _typed(hit["value"])
    return {"name": name, "arguments": arguments}


def instead_say(text: str) -> str:
    """What to show in place of the markup.

    Names the tool when the markup named one, because "I tried to run
    terminal_run" is something the user can act on and "something went wrong"
    is not.
    """
    tool = reached_for(text)
    what = f"call {tool}" if tool else "use a tool"
    return (
        f"I tried to {what} and the call did not go through — my end wrote it out "
        "instead of running it. Nothing was done. Ask me again and I will retry it."
    )
