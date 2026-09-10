"""The first run.

The temptation is to download everything before saying hello. That is a bad
first run: several gigabytes of models between someone opening Marvi and Marvi
being any use at all, most of it for capabilities they may not want.

So this computes the **minimum** — what is genuinely required before the first
sentence — and offers the rest.

## What is actually required

One provider, and nothing else. Marvi can think, chat, remember and use every
local tool with a provider and no models at all. Voice needs several gigabytes;
vision needs a camera and a face model. Both are additions to a working
assistant, not prerequisites for one.

The GPU question comes before any of it, because it decides which PyTorch build
gets installed and answering it afterwards means a multi-gigabyte reinstall.

## Steps are computed, not scripted

Each step reports whether it is already done, so re-running is honest on a
half-set-up machine and the flow can be resumed rather than restarted. Nothing
here installs anything: it returns what to do, and the page or CLI does it.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..identity import IdentityFiles
from ..providers import configured_profiles
from . import catalog, hardware


@dataclass
class Step:
    key: str
    title: str
    #: Why it matters, in one line, in the user's terms.
    why: str
    done: bool
    #: True when Marvi genuinely cannot work without it.
    required: bool
    action: str = ""
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "title": self.title,
            "why": self.why,
            "done": self.done,
            "required": self.required,
            "action": self.action,
            "detail": self.detail,
        }


def _capability_step(
    repo_root: Path, capability: str, title: str, why: str
) -> Step:
    # Every component, not only the ones with a file map.
    #
    # This filtered on `c.files`, and a command-kind component has none -- it
    # owns its own download. The browser capability has exactly one component,
    # `playwright-browsers`, which is command-kind, so the filter emptied the
    # list and the step read "nothing to download yet" for ever, done=False,
    # with no way to act on it. Meanwhile Chromium really was missing and the
    # browser tools failed at `start_dependencies` with nothing to connect the
    # two. `installer.state_of` already knows how to check a command; this
    # simply asks it.
    from . import installer

    components = catalog.for_capability(repo_root, capability)
    if not components:
        return Step(
            key=capability, title=title, why=why, done=True, required=False,
            action=f"marvi setup {capability}", detail="nothing to install",
        )
    # `deep=True`, and the cost is the point. With `deep=False` a command
    # component reports `installed: True, "not checked"` -- so this screen,
    # whose entire job is to say what is missing, would have said "ready" over
    # an engine that was not there. Measured at 1.8s for the one component
    # that actually runs a check on Windows.
    states = [(one, installer.state_of(one, repo_root, deep=True)) for one in components]
    missing = [one for one, state in states if not state["installed"]]
    size = sum(one.bytes_total for one in missing)
    if size:
        detail = f"{size / 1024**3:.1f} GB to download"
    elif missing:
        # A command component knows its own size and this does not, so say
        # what the manifest says rather than inventing a number.
        notes = [str(one.extra.get("note") or "") for one in missing]
        detail = next((note for note in notes if note), "not installed")
    else:
        detail = "ready"
    return Step(
        key=capability,
        title=title,
        why=why,
        done=not missing,
        required=False,
        action=f"marvi setup {capability}",
        detail=detail,
    )


def steps(repo_root: Path) -> list[Step]:
    """What is left to do, in the order it should be done."""
    found = hardware.detect()
    gpu = hardware.question(found)
    identity = IdentityFiles().read()
    providers = [p.name for p in configured_profiles()]

    return [
        Step(
            key="hardware",
            title="Choose GPU or CPU",
            why=(
                "It decides which build of PyTorch gets installed. Answering "
                "later means downloading it all again."
            ),
            # Nothing to answer when there is no usable GPU.
            done=not gpu["ask"],
            required=False,
            action="marvi gpu",
            detail=gpu.get("reason", ""),
        ),
        Step(
            key="provider",
            title="Connect a provider",
            why="Marvi cannot think without a model behind it.",
            done=bool(providers),
            # The only genuinely required step. Everything else is an addition.
            required=True,
            action="Providers page, or start Ollama locally",
            detail=", ".join(providers) if providers else "none connected",
        ),
        _capability_step(
            repo_root,
            "voice",
            "Install the voice models",
            "Only needed if you want to talk to Marvi rather than type.",
        ),
        _capability_step(
            repo_root,
            "vision",
            "Install the vision model",
            "Only needed if you want Marvi to recognise faces.",
        ),
        Step(
            key="identity",
            title="Say who you are",
            why=(
                "Marvi fills this in by listening, so there is nothing to do "
                "here — it is listed so you know it exists and can edit it."
            ),
            done=bool(identity.user.strip()) and "Not known yet" not in identity.user,
            required=False,
            action="Identity page",
            detail="Marvi asks one thing at a time, rarely",
        ),
    ]


def status(repo_root: Path) -> dict[str, Any]:
    """Whether Marvi is usable yet, and what would make it more so."""
    found = steps(repo_root)
    blocking = [s for s in found if s.required and not s.done]
    optional = [s for s in found if not s.required and not s.done]
    return {
        "steps": [s.as_dict() for s in found],
        # The distinction that keeps a first run short: usable is not the same
        # as complete, and Marvi is usable with one provider and no models.
        "usable": not blocking,
        "blocking": [s.key for s in blocking],
        "suggested": [s.key for s in optional],
        "complete": not blocking and not optional,
    }
