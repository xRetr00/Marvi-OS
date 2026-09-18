"""`@notes.md` and `@https://…` in a typed message.

Marvi could always read a file or fetch a page -- as a tool call, after
deciding to, which costs a round trip and sometimes does not happen at all
("I don't have access to that file"). Naming the thing in the message is the
shorter path, and it is how many coding agents'
`@` work (design reference only; nothing is copied).

Two rules the implementation exists to keep:

* **A mention becomes an attachment, not prose.** The same rows the file picker
  creates, so validation, the provider shape, the attachment chips in the
  window, the Markdown export and `chat_search` all keep working with no second
  path to maintain.
* **What comes back is data.** A file or a page reached this way is wrapped as
  untrusted external content exactly like one Marvi fetched herself; `@` in a
  message is not a way to put instructions in front of the model.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from .logs import get_logger

log = get_logger("chat")

#: `@path`, `@"two words.md"` or `@https://…`, not an email address and not the
#: middle of a word. Stops at whitespace, and at the trailing punctuation a
#: sentence leaves behind ("look at @notes.md, please").
MENTION = re.compile(r'(?:^|(?<=\s))@(?:"([^"]+)"|([^\s,;)]+))')

#: Per turn. Four files is a generous reading of "have a look at these"; forty
#: is a paste accident, and every one of them costs tokens.
MAX_MENTIONS = 4

#: Text pulled from a page. Whole-page extraction can be a novel.
MAX_PAGE_CHARS = 20_000


def parse(text: str) -> list[str]:
    """Every distinct thing mentioned, in the order it was written."""
    found: list[str] = []
    for match in MENTION.finditer(text or ""):
        one = (match.group(1) or match.group(2) or "").strip()
        if one and one not in found:
            found.append(one)
    return found[:MAX_MENTIONS]


def _is_url(one: str) -> bool:
    return one.lower().startswith(("http://", "https://"))


def resolve(
    text: str,
    thread_id: str,
    store: Any,
    workspace: Any = None,
    web: Any = None,
) -> tuple[list[str], list[str]]:
    """Turn the mentions in `text` into attachments on `thread_id`.

    Returns the new attachment ids and one note per mention that could not be
    read -- said back to the user rather than swallowed, because a silently
    ignored `@` looks exactly like Marvi refusing to look at the file.
    """
    attachment_ids: list[str] = []
    notes: list[str] = []
    for one in parse(text):
        try:
            if _is_url(one):
                if web is None:
                    notes.append(f"{one}: web access is not configured")
                    continue
                page = web.extract(one)
                body = str(
                    (page or {}).get("text") or (page or {}).get("content") or ""
                ).strip()
                if not body:
                    notes.append(f"{one}: nothing could be read from that page")
                    continue
                # The attachment store keeps a file *name*, so a URL has to
                # become one: the host and path, which is what a person
                # recognises in the attachment chip a month later.
                from urllib.parse import urlparse

                parsed = urlparse(one)
                stem = re.sub(r"[^A-Za-z0-9._-]+", "-", f"{parsed.netloc}{parsed.path}").strip("-")
                row = store.add_attachment(
                    thread_id,
                    f"{stem[:60] or 'page'}.txt",
                    "text/plain",
                    body[:MAX_PAGE_CHARS].encode("utf-8"),
                )
            else:
                if workspace is None:
                    notes.append(f"{one}: no workspace folder is set")
                    continue
                target = workspace.resolve(one)
                if not target.is_file():
                    notes.append(f"{one}: not a file in the workspace")
                    continue
                data = target.read_bytes()
                # A code or config file has no media type the attachment store
                # accepts; it is text, and saying so is the whole fix.
                media_type = ""
                if target.suffix.lower() in (".png", ".jpg", ".jpeg", ".webp", ".gif", ".pdf",
                                             ".docx", ".xlsx", ".pptx"):
                    media_type = ""
                else:
                    media_type = "text/plain"
                row = store.add_attachment(thread_id, Path(one).name, media_type, data)
        except Exception as exc:  # a bad mention must never take the turn down
            notes.append(f"{one}: {exc}")
            log.info("mention could not be read", extra={"marvi_mention": one[:120]})
            continue
        attachment_ids.append(str(row["id"]))
    return attachment_ids, notes
