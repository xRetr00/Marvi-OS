"""Which model does which job.

Marvi has one model chosen for the hardest thing she does -- holding a
conversation -- and provider-owned auxiliary defaults for smaller jobs. Most
of what she runs is not a conversation: deciding whether a background event is
worth mentioning is a one-sentence yes or no, summarising a fetched page needs
no reasoning at all, and both happen far more often than a hard question.

So each of those jobs is a *role*, and a role may name its own provider and
model. Unset means `auto`, and auto means **the main model** -- the same one
the conversation uses. It did not, once: `job="aux"` resolved to a hardcoded
`default_aux_model` per provider, so every background job ran on a model
nobody had chosen while the page said each was on auto.

## Why roles rather than one "auxiliary" switch

There was already a three-way `main` / `aux` / `vision` split inside the
provider profiles, with the aux model hardcoded per provider and no way for
anyone to change it. That is the right shape and the wrong granularity: the
model you want for a yes/no verdict is not the model you want for a spoken
turn, and neither is the one you want for a picture. Naming the jobs is what
lets them differ.

## What a role is not

It is not a fallback and not a router. Nothing here decides *whether* to call a
model, only which one answers when a call is already being made. A role that is
unset costs nothing and changes nothing.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

from .logs import get_logger

log = get_logger("providers")

#: How a role is written down: `provider/model`, or empty for auto.
#:
#: One string rather than two settings because they are meaningless apart -- a
#: model without its provider names nothing -- and because it makes "unset"
#: unambiguous.
SEPARATOR = "/"


@dataclass(frozen=True)
class Role:
    key: str
    title: str
    #: What it is for, in the words of somebody deciding whether to change it.
    why: str
    #: What choosing well buys. Empty when the honest answer is "not much".
    gain: str = ""

    @property
    def setting(self) -> str:
        return f"MARVI_AUX_{self.key.upper()}"

    @property
    def effort_setting(self) -> str:
        """How hard the chosen model should think, when it can.

        Its own setting rather than a third field in `provider/model`, because
        it is a property of the model and not of the pairing: change the model
        and an effort that no longer applies should stop applying, which is
        what an empty value here does.
        """
        return f"MARVI_AUX_{self.key.upper()}_EFFORT"


#: Every job Marvi runs a model for, other than the conversation itself.
#:
#: Deliberately only the ones that exist. A role for a feature nobody has built
#: is a setting that does nothing, and a settings page full of those teaches
#: people not to read it.
ROLES: tuple[Role, ...] = (
    Role(
        key="voice",
        title="Voice",
        why="The spoken conversation. Latency here is the thing you feel most.",
        gain="A faster model shortens every reply, and reasoning is off for voice anyway.",
    ),
    Role(
        key="vision",
        title="Vision",
        why="Reading an image: a screenshot, a photo, a page you showed her.",
        gain="The main model may not accept images at all, in which case this is required.",
    ),
    Role(
        key="mind",
        title="Background mind",
        why="Deciding whether something that happened is worth saying out loud.",
        gain="A one-sentence verdict, many times an hour. The cheapest real saving here.",
    ),
    Role(
        key="memory",
        title="Memory",
        why="Promoting what keeps coming up into a fact worth keeping.",
        gain="Runs on a timer, nobody waiting. Summarising needs no reasoning.",
    ),
    Role(
        key="web",
        title="Web reading",
        why="Pulling the part you asked about out of a fetched page.",
        gain="Long input, short output, no reasoning. A cheap long-context model fits.",
    ),
    Role(
        key="title",
        title="Conversation titles",
        why="Naming a thread from its first message.",
        gain="Nobody waits for a title, so nothing is lost by making it small.",
    ),
)

#: Roles that would make sense and have nowhere to plug in yet.
#:
#: Empty, and worth keeping as a reminder of the rule: a setting for a call
#: that is never made reads as a knob, does nothing, and teaches people the
#: page is decorative. A role arrives with its call site.
NOT_YET: tuple[str, ...] = ()

BY_KEY = {role.key: role for role in ROLES}


def configured(key: str) -> str:
    """The raw setting for a role, or "" when it is on auto."""
    role = BY_KEY.get(key)
    return os.environ.get(role.setting, "").strip() if role else ""


def resolve(key: str) -> tuple[str, str]:
    """`(provider, model)` for a role, or `("", "")` to use the main model.

    A malformed value resolves to auto rather than raising. This sits on the
    path of every background call, and a typo in a settings field must not be
    able to stop Marvi thinking.
    """
    raw = configured(key)
    if not raw:
        return "", ""
    provider, _, model = raw.partition(SEPARATOR)
    provider, model = provider.strip(), model.strip()
    if not provider or not model:
        log.warning("auxiliary role %s is set to %r, which names no model; using the main", key, raw)
        return "", ""
    return provider, model


def effort(key: str) -> str:
    """The reasoning effort chosen for a role, or "" for the model's own default."""
    role = BY_KEY.get(key)
    if role is None:
        return ""
    chosen = os.environ.get(role.effort_setting, "").strip().lower()
    # Only meaningful alongside a chosen model. An effort left behind after a
    # role goes back to auto would silently apply to the main model.
    return chosen if chosen and configured(key) else ""


def overrides(key: str) -> dict[str, str]:
    """Keyword arguments for direct `ProviderClient.call`, empty on auto.

    Returned as kwargs to splat so a call site reads the same whether or not a
    role is configured, and so adding a role to a call is one line.
    """
    provider, model = resolve(key)
    return {"provider": provider, "model": model} if provider else {}


def fallback_overrides(key: str) -> dict[str, str]:
    """Routing kwargs for ``call_with_fallback`` and ``stream_with_fallback``.

    Those methods choose a provider through ``preferred`` and then pass the
    resolved profile to ``call`` themselves. Supplying ``provider`` in their
    kwargs would pass it twice and fail before any model request was made.
    """
    provider, model = resolve(key)
    if not provider:
        return {}
    chosen: dict[str, str] = {"preferred": provider, "model": model}
    if picked := effort(key):
        chosen["effort"] = picked
    return chosen


def status(available: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    """Every role and what it currently resolves to, for the settings page."""
    rows = []
    for role in ROLES:
        provider, model = resolve(role.key)
        rows.append(
            {
                "key": role.key,
                "title": role.title,
                "why": role.why,
                "gain": role.gain,
                "setting": role.setting,
                "provider": provider,
                "model": model,
                "effort": effort(role.key),
                "effort_setting": role.effort_setting,
                "auto": not provider,
            }
        )
    return {
        "roles": rows,
        "separator": SEPARATOR,
        "providers": available or [],
        # So the page can say which jobs are pinned away from it. A job left on
        # a provider you have stopped using goes on spending there quietly, and
        # nothing said so.
        "main": os.environ.get("MARVI_PROVIDER", "").strip(),
    }
