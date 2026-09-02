---
name: reading-things-aloud
description: How to say something out loud that does not want to be spoken - a list, a URL, a file path, code, a long number, a size in bytes, a timestamp, a table, or search results. Use when the answer you are about to speak contains any of those, or when the user asks you to read something back to them. Not for ordinary sentences, and not a reason to shorten an answer that was already speakable.
license: MIT
metadata:
  author: Marvi OS
  version: "1.0"
---

# Reading things aloud

The user cannot scroll back and cannot see punctuation. Anything shaped for the
eye has to be reshaped before it is spoken.

## Lists

Say them as a sentence, with the count first: "three of them: the gateway, the
agent, and the room."

More than about four items, do not read them all. Say how many, say the ones
that matter, offer the rest: "eleven logs — the useful ones are errors, agent
and gateway. Want the whole list?"

## Numbers

Round for the ear, and use the unit a person would use.

| On screen | Out loud |
| --- | --- |
| 2,516 MB | about two and a half gigabytes |
| 13.7% | just under fourteen percent |
| 3346ms | three and a third seconds |
| 0.4.15 | zero point four point fifteen |
| 17842 | one seven eight four two (read digits for ports and IDs) |

Say a version or an identifier digit by digit. Say a quantity as a quantity.

## Times and dates

"Quarter past four", "last Tuesday", "three days ago". Never read a timestamp
as it is written. If the exact value matters, offer to put it in the chat.

## URLs, paths, keys

Do not read them. Say what the thing *is* and where it went:

- a link → "I put the link in the chat"
- a file → the file name only, never the directory chain
- an API key, token or password → never, in any form, even partially

## Code and errors

Do not read code out. Say what it does, or what the error means, in a
sentence. If they need the text, it belongs in the chat window.

An exception is worth one sentence: what failed and why. Not the traceback.

## Search results and quotes

Say the answer, then where it came from: "reuters says the deal closed
yesterday." Never read a headline list. If several sources disagree, say that
rather than picking one silently.

## When it will not fit

Say the short version out loud and offer the rest, rather than speaking a long
answer the user cannot stop or re-read. Ending on a question is fine; ending on
minute four is not.
