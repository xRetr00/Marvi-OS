"""Reading a skill before Marvi does.

A skill's Markdown legitimately shapes behaviour -- that is what it is for, and
it is why the body cannot be wrapped in an untrusted envelope the way a fetched
web page is. The consequence is that installing one is the widest thing a user
can do to Marvi in a single click, and the whole control was a wall of Markdown
shown on screen with an Install button under it. "You were shown it" is not a
control; nobody reads five hundred lines before clicking.

Every externally sourced skill is scanned and assigned a **trust tier**, and
both halves matter. The scan alone would either block first-party skills over
harmless phrasing or wave through a gist because its wording was careful.

    bundled    ships with Marvi. Not scanned.
    trusted    sources the user named as trusted. Cautions are shown, not blocked.
    community  everything else. Any finding blocks unless the user overrides.

## What it can and cannot do

Patterns over text. It catches the known shapes -- exfiltration, instructions
aimed at the operator, "ignore your previous instructions", persistence, mass
deletion -- and it will not catch a careful author who means harm. It is a
tripwire, not a proof, and it is written to say so: findings are shown with
what matched, so a person can judge rather than trust a verdict.

Never blocks on its own. It returns findings; the install screen decides, and
the user can always override on a source they trust. A scanner that silently
refuses is a scanner people route around.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

BUNDLED, TRUSTED, COMMUNITY = "bundled", "trusted", "community"

#: Severity, pattern, and what it would mean. The explanation is the product:
#: a finding nobody can act on is noise, and noise is what teaches people to
#: click through.
RULES: tuple[tuple[str, str, str, str], ...] = (
    (
        "danger",
        "prompt-injection",
        r"\b(ignore|disregard|forget)\s+(all\s+|your\s+|any\s+)*(previous|prior|earlier|above)\s+"
        r"(instructions?|rules?|prompts?)",
        "Tells the model to disregard its own instructions. A skill has no "
        "legitimate reason to say this.",
    ),
    (
        "danger",
        "identity-override",
        r"\byou\s+are\s+(now\s+)?(no\s+longer\s+)?(not\s+)?"
        r"(marvi|an?\s+different\s+assistant|in\s+developer\s+mode)",
        "Tries to replace who Marvi is, rather than tell her how to do a task.",
    ),
    (
        "danger",
        "secret-exfiltration",
        r"(send|post|upload|email|transmit|exfiltrat\w*)\b[^.\n]{0,60}"
        r"\b(api[_\s-]?key|token|password|credential|\.env|secret)",
        "Moves credentials somewhere. Reading a secret is a setting the user "
        "turns on; sending one elsewhere is not.",
    ),
    (
        "danger",
        "destructive-command",
        r"(rm\s+-rf\s+[/~]|Remove-Item[^\n]{0,40}-Recurse[^\n]{0,40}-Force|format\s+[a-z]:|"
        r"del\s+/s\s+/q\s+[a-z]:)",
        "Deletes broadly enough to take things nobody meant to lose.",
    ),
    (
        "danger",
        "persistence",
        r"(CurrentVersion\\\\?Run|schtasks\s+/create|crontab\s+-|systemctl\s+enable|"
        r"LaunchAgents)",
        "Arranges to run again after a restart, which a skill does not need to do.",
    ),
    (
        "caution",
        "remote-execution",
        r"(curl|wget|iwr|Invoke-WebRequest)[^\n]{0,80}\|\s*(bash|sh|iex|python)",
        "Downloads something and runs it. What runs is decided elsewhere and "
        "can change after you read this.",
    ),
    (
        "caution",
        "hidden-from-the-user",
        r"\b(do\s+not|don'?t|never)\s+(tell|inform|mention\s+to|show)\s+"
        r"(the\s+)?(user|them|him|her)\b",
        "Asks Marvi to keep something from you.",
    ),
    (
        "caution",
        "credential-reading",
        r"\b(read|open|cat|Get-Content)\b[^\n]{0,40}"
        r"(\.env|id_rsa|credentials|\.aws|providers\.env)",
        "Reads somewhere credentials live. Legitimate for some skills, and "
        "worth knowing about.",
    ),
    (
        "caution",
        "wide-shell-use",
        r"```(bash|sh|powershell|cmd)\b",
        "Contains shell commands. They still run through Marvi's tool "
        "boundary, so this is a note rather than a problem.",
    ),
)

COMPILED = tuple(
    (severity, name, re.compile(pattern, re.IGNORECASE), why)
    for severity, name, pattern, why in RULES
)


@dataclass(frozen=True)
class Finding:
    severity: str
    rule: str
    why: str
    #: The text that matched, so a person can judge rather than take a verdict.
    quote: str

    def as_dict(self) -> dict[str, Any]:
        return {"severity": self.severity, "rule": self.rule, "why": self.why, "quote": self.quote}


def scan(body: str) -> list[Finding]:
    """Everything worth mentioning about this skill's text, worst first."""
    found: list[Finding] = []
    for severity, name, pattern, why in COMPILED:
        match = pattern.search(body or "")
        if match is None:
            continue
        quote = " ".join(match.group(0).split())[:160]
        found.append(Finding(severity=severity, rule=name, why=why, quote=quote))
    return sorted(found, key=lambda f: 0 if f.severity == "danger" else 1)


def tier(source: str, trusted_sources: tuple[str, ...] = ()) -> str:
    """How much benefit of the doubt this source gets.

    Matched on prefix so a whole repository can be trusted without listing
    every skill in it.
    """
    if source in ("bundled", "", "marvi"):
        return BUNDLED
    clean = source.strip().lower()
    return (
        TRUSTED
        if any(clean.startswith(t.strip().lower()) for t in trusted_sources if t.strip())
        else COMMUNITY
    )


def verdict(body: str, source: str, trusted_sources: tuple[str, ...] = ()) -> dict[str, Any]:
    """What the install screen should do with this.

    `blocked` is advice, not enforcement: the route still installs when the
    user says so, because a scanner people cannot override is a scanner they
    stop using. What it buys is that the default answer for an unknown source
    with a serious finding is no.
    """
    level = tier(source, trusted_sources)
    if level == BUNDLED:
        return {"tier": level, "findings": [], "blocked": False, "reason": "ships with Marvi"}

    found = scan(body)
    dangers = [f for f in found if f.severity == "danger"]
    if level == TRUSTED:
        blocked = bool(dangers)
        reason = (
            "a trusted source, but this is not a thing a skill does"
            if blocked
            else "a source you trust"
        )
    else:
        blocked = bool(found)
        reason = "from a source you have not marked as trusted" if found else "nothing matched"
    return {
        "tier": level,
        "findings": [f.as_dict() for f in found],
        "blocked": blocked,
        "reason": reason,
    }
