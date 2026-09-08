"""Whether the browser is switched on.

All that is left of this module. It used to hold a browser of its own — one
long-lived Playwright page, driven from synchronous tool handlers, with eight
tools of its own: `browser_open`, `browser_read`, `browser_click`,
`browser_type`, `browser_back`, `browser_links`, `browser_screenshot`,
`browser_close`.

That browser was replaced by `browser_workspace`, which has sessions, tabs,
profiles, private login handoff and an embedded host — and the old one was
never removed. Nothing registered its tools any more, so it was dead code, but
it was not harmless dead code: it left a second vocabulary for the same job
sitting in the tree, with `browser_read` in it while the live call is
`browser_action(read)`. The model reached for the shape it half-recognised and
called `browser_control command=read`, which is a command on neither.

What survives is the switch, because it is genuinely about the feature rather
than about either implementation.
"""

from __future__ import annotations

import os


def browser_enabled() -> bool:
    """Off unless asked for: a browser is a real resource cost.

    Left as an environment switch rather than a setting because it decides
    whether a whole subsystem starts, and a subsystem that appears halfway
    through a session is harder to reason about than one that was there or
    was not.
    """
    return os.environ.get("MARVI_BROWSER", "").strip().lower() in ("1", "true", "on", "yes")
