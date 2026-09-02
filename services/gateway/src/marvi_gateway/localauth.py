"""The one door that hands out a credential, and what stands at it.

`/providers/voice` answers with the provider's raw API key. It has to: the
Agent runs in its own process, holds the credential, and calls the provider
directly -- that is what keeps the model's first token off a second hop. But
the endpoint had nothing in front of it, so anything that could reach loopback
could read the key with one unauthenticated GET.

Loopback is not a boundary. Two things reach it that are not the Agent:

* **Any page in any browser on this machine.** `fetch("http://127.0.0.1:8765
  /providers/voice")` from a tab the user has open is a cross-origin request
  the browser will happily make, and without a CORS response the *reply* is
  hidden from the page -- but a request that leaks through a redirect, an
  extension, or a `no-cors` variant is not something to rely on the browser to
  prevent. It is also exactly the DNS-rebinding shape.
* **Any other process running as this user.**

Two checks, because they stop different things.

`MARVI_LOCAL_TOKEN` is a per-launch secret the desktop puts in the environment
of every child it starts. The Agent has it because it was started by the same
supervisor; a browser tab and an unrelated process do not. When it is unset --
a developer running the Gateway by hand, the eval harness -- the check is not
enforced, because a token nobody issued cannot be required without breaking
every way of running this outside the app. That is a deliberate limit: the
guard is worth having in the shipped configuration and is not a claim to be
airtight outside it.

`Sec-Fetch-Site` is sent by every modern browser on every request it makes and
by no ordinary HTTP client. Its presence means a browser engine is asking, and
nothing that should be reading a credential is a browser. This one is enforced
always, token or no token, because it costs nothing and closes the drive-by.
"""

from __future__ import annotations

import hmac
import os

from fastapi import HTTPException, Request

from .logs import get_logger

log = get_logger("gateway")

SETTING = "MARVI_LOCAL_TOKEN"

HEADER = "x-marvi-local"

#: Where the desktop also leaves the token, for a Gateway it did not start.
#:
#: The environment is the better channel and stays primary. It is not the only
#: one that can be right, because a Gateway is not always started by the
#: desktop that is currently using it: relaunch while an old Gateway still
#: holds port 8765 with a live parent and the new desktop adopts it. The
#: adopted Gateway then checks a token from the previous launch while the new
#: Agent presents the current one, and every request for the provider
#: credential is refused. The log has 285 of those and a voice job that died
#: four seconds after the first.
#:
#: Both are accepted, because both were written by a desktop that owns this
#: install. What this costs: a same-user process can read the file, where
#: reading another process's environment takes a handle and a little more
#: effort. That is a difference of degree inside a threat this guard already
#: says it does not close -- see the note on `MARVI_LOCAL_TOKEN` above. The
#: check that actually stops the drive-by is `Sec-Fetch-Site`, and it is
#: unaffected.
TOKEN_FILE = "state/local-token"


def _from_file() -> str:
    from .paths import root

    try:
        return (root() / TOKEN_FILE).read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def expected() -> list[str]:
    """Every token this Gateway will accept. Empty when the guard is disabled."""
    return [token for token in (os.environ.get(SETTING, "").strip(), _from_file()) if token]


def from_a_browser(request: Request) -> bool:
    """Whether a browser engine made this request.

    `Sec-Fetch-Site` is a forbidden header name: page script cannot set or
    remove it, which is what makes it worth checking. `same-origin` is a page
    served by this Gateway asking for its own resources, which is the one
    browser case that is not a drive-by.
    """
    site = request.headers.get("sec-fetch-site", "").strip().lower()
    return bool(site) and site != "same-origin"


def guard(request: Request) -> None:
    """Raise unless this caller may be handed a credential."""
    if from_a_browser(request):
        log.warning("refused a browser request for a credential")
        raise HTTPException(status_code=403, detail="not available to a browser")
    wanted = expected()
    if not wanted:
        return
    offered = request.headers.get(HEADER, "")
    # `compare_digest` rather than `==`: the comparison is against a secret and
    # a local attacker can time it as easily as a remote one. Every candidate
    # is checked rather than stopping at the first match, so the work does not
    # depend on which one it was.
    if not any(hmac.compare_digest(offered, token) for token in wanted):
        log.warning(
            "refused an unauthenticated request for %s -- the caller's token "
            "matches neither the one this Gateway was started with nor the one "
            "on disk. Usually a Gateway left running from an earlier launch; "
            "restart Marvi so both are started together.",
            # `getattr`: the path is for the log line and nothing else, and a
            # guard that raises while reporting a refusal refuses nothing.
            getattr(getattr(request, "url", None), "path", "a guarded endpoint"),
        )
        raise HTTPException(status_code=403, detail="a local token is required")
