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
    components = catalog.for_capability(repo_root, capability)
    downloadable = [c for c in components if c.files]
    missing = [c for c in downloadable if not c.status()["installed"]]
    size = sum(c.bytes_total for c in missing)
    return Step(
        key=capability,
        title=title,
        why=why,
        done=bool(downloadable) and not missing,
        required=False,
        action=f"marvi setup {capability}",
        detail=(
            f"{size / 1024**3:.1f} GB to download"
            if size
            else ("ready" if downloadable else "nothing to download yet")
        ),
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
