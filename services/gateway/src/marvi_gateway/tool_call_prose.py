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
