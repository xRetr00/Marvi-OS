"""What Marvi can install, described as data.

`config/voice-models.json` already had the right shape — an id, a pinned
revision, and a file map of `{name: [size, sha256]}`. This generalises that to
everything else rather than inventing a second format.

A component is **data, not code**. Adding one means adding an entry to
`config/components.json`; nothing in this package knows the name of a specific
model. That is the same rule the provider registry follows, for the same
reason.

## Two files during the transition

Voice models are still read from `config/voice-models.json`, because the
PowerShell installers read it too and duplicating five SHA256 hashes across two
files is how they drift apart. When those scripts are retired the entries move
here and the seam disappears. Everything else lives in `components.json`.

## Verification is not optional

A download is not finished until its hash matches. A truncated model produces a
baffling runtime error hours later, in a completely different subsystem; a hash
check produces a clear one immediately. Size is checked first because it is free
and catches the common case.
"""

from __future__ import annotations

import hashlib
import json
import os
import platform
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from ..logs import get_logger

log = get_logger("setup")

Kind = Literal["model", "binary", "python", "mcp", "skill"]

# Where installed components live. Everything Marvi installs goes under here so
# `remove` is honest and an uninstall leaves nothing behind.
def install_root() -> Path:
    configured = os.environ.get("MARVI_INSTALL_ROOT", "").strip()
    if configured:
        return Path(configured)
    from ..paths import root

    return root()


@dataclass(frozen=True)
class FileSpec:
    """One file, with the two checks that matter."""

    path: str
    size: int
    sha256: str

    def verify(self, base: Path, deep: bool = True) -> tuple[bool, str]:
        """Check one file. `deep` hashes it; shallow checks presence and size.

        Hashing a 2.4 GB model takes about two and a half seconds. That is fine
        on the Setup page, where the user asked, and ruinous on the health
        endpoint the shell polls every two seconds — which is what it was doing,
        and why the Gateway went unavailable while a model downloaded: it was
        busy re-hashing the file being written.

        Size still catches the common failure. An interrupted download is short;
        a corrupt one is the rarer case and worth a slower, explicit check.
        """
        target = base / self.path
        if not target.exists():
            return False, "missing"
        actual_size = target.stat().st_size
        if self.size and actual_size != self.size:
            # Cheap, and catches the common failure: an interrupted download.
            return False, f"wrong size ({actual_size} vs {self.size})"
        if deep and self.sha256:
            digest = hashlib.sha256()
            with target.open("rb") as handle:
                for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                    digest.update(chunk)
            if digest.hexdigest().lower() != self.sha256.lower():
                return False, "hash mismatch"
        return True, "ok"


@dataclass(frozen=True)
class Component:
    name: str
    kind: Kind
    title: str
    #: Why someone would want this, in one line. Shown before a large download.
    why: str
    #: Which capabilities stop working without it. Empty means optional extra.
    needed_for: tuple[str, ...] = ()
    #: True for the handful of things Marvi cannot start without — the Python
    #: environments, and the LiveKit server that carries the voice session.
    #: The installer installs exactly these and leaves the rest to the user,
    #: because everything else is either large or a trust decision.
    essential: bool = False
    #: `huggingface` and `url` are downloadable; `command` is run.
    source_type: str = "huggingface"
    source_id: str = ""
    revision: str = ""
    base_url: str = ""
    install_to: str = ""
    files: tuple[FileSpec, ...] = ()
    #: For `python`: the uv project to sync.
    project: str = ""
    #: For `git`: the one subdirectory to check out, and the files to keep.
    subdirectory: str = ""
    pattern: str = "*"
    #: For an archive: the file the download must produce once unpacked. The
    #: archive itself is deleted afterwards, so this — not the download — is
    #: what "installed" means for these.
    binary: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def bytes_total(self) -> int:
        return sum(spec.size for spec in self.files)

    def target(self) -> Path:
        return install_root() / (self.install_to or self.name)

    def url_for(self, spec: FileSpec) -> str:
        if self.source_type == "huggingface":
            return (
                f"https://huggingface.co/{self.source_id}/resolve/"
                f"{self.revision}/{spec.path}"
            )
        if self.source_type == "url":
            return f"{self.base_url.rstrip('/')}/{spec.path}"
        raise ValueError(f"{self.name} is not downloadable ({self.source_type})")

    def status(self, deep: bool = True) -> dict[str, Any]:
        """Installed, partly installed, or missing — with the reason per file.

        `deep=False` skips hashing, for callers on a hot path. See
        `FileSpec.verify`.
        """
        if self.binary:
            # The archive is verified on the way in and then thrown away, so
            # the unpacked binary is the only thing left to check.
            target = self.target() / self.binary
            if target.exists() and target.stat().st_size > 0:
                return {"installed": True, "detail": "unpacked", "problems": []}
            return {"installed": False, "detail": "not installed", "problems": []}
        if self.source_type == "git" and not self.files:
            # A subdirectory checkout has no published hashes to check against,
            # so presence is the only honest check. Said plainly rather than
            # dressed up as verification.
            target = self.target()
            found = sorted(target.glob(self.pattern)) if target.exists() else []
            if found:
                return {
                    "installed": True,
                    "detail": f"{len(found)} file(s) present (not hash-verified)",
                    "problems": [],
                }
            return {"installed": False, "detail": "not installed", "problems": []}
        if not self.files:
            return {"installed": False, "detail": "nothing to verify", "problems": []}
        base = self.target()
        problems = []
        for spec in self.files:
            ok, reason = spec.verify(base, deep=deep)
            if not ok:
                problems.append({"file": spec.path, "reason": reason})
        if not problems:
            return {
                "installed": True,
                "detail": "verified" if deep else "present",
                "problems": [],
            }
        if len(problems) == len(self.files):
            return {"installed": False, "detail": "not installed", "problems": problems}
        return {
            "installed": False,
            "detail": f"{len(problems)} of {len(self.files)} files bad",
            "problems": problems,
        }


def _platform_key() -> str:
    machine = platform.machine().lower()
    arch = "arm64" if machine in {"arm64", "aarch64"} else "amd64"
    return f"{sys.platform.replace('win32', 'windows')}-{arch}"


def _files_from(mapping: dict[str, Any], prefix: str = "") -> tuple[FileSpec, ...]:
    return tuple(
        FileSpec(path=f"{prefix}{name}", size=int(value[0]), sha256=str(value[1]))
        for name, value in (mapping or {}).items()
    )


def _voice_components(repo_root: Path) -> list[Component]:
    """Read the voice models from the file the PowerShell installers also use."""
    path = repo_root / "config" / "voice-models.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []

    stt, tts = manifest.get("stt") or {}, manifest.get("tts") or {}
    components: list[Component] = []
    if stt:
        subdirectory = stt.get("subdirectory", "")
        components.append(
            Component(
                name="voice-stt",
                kind="model",
                title="Speech recognition",
                why="Marvi cannot hear you without it.",
                needed_for=("voice",),
                source_id=stt.get("id", ""),
                revision=stt.get("revision", ""),
                install_to="models/stt/parakeet-tdt-0.6b-v3-onnx",
                files=_files_from(
                    stt.get("files"), f"{subdirectory}/" if subdirectory else ""
                ),
                extra={"language": stt.get("language", "")},
            )
        )
    if tts:
        components.append(
            Component(
                name="voice-tts",
                kind="model",
                title="Speech synthesis",
                why="Marvi cannot speak without it.",
                needed_for=("voice",),
                source_id=tts.get("id", ""),
                revision=tts.get("revision", ""),
                install_to="models/tts/kokoro-82m",
                files=_files_from(tts.get("files")),
                extra={"default_voice": tts.get("default_voice", "")},
            )
        )
    return components


def _component_from(raw: dict[str, Any]) -> Component:
    source = raw.get("source") or {}
    return Component(
        name=str(raw["name"]),
        kind=raw.get("kind", "model"),
        title=raw.get("title", raw["name"]),
        why=raw.get("why", ""),
        needed_for=tuple(raw.get("needed_for", ())),
        essential=bool(raw.get("essential", False)),
        source_type=source.get("type", "huggingface"),
        source_id=source.get("id", ""),
        revision=source.get("revision", ""),
        base_url=source.get("base_url", ""),
        install_to=raw.get("install_to", ""),
        files=_files_from(_for_this_platform(raw)),
        project=raw.get("project", ""),
        subdirectory=(raw.get("extra") or {}).get("subdirectory", ""),
        pattern=(raw.get("extra") or {}).get("pattern", "*"),
        binary=raw.get("binary", ""),
        extra=raw.get("extra", {}),
    )


def _for_this_platform(raw: dict[str, Any]) -> dict[str, Any]:
    """Pick this machine's files, for a component that publishes per-platform.

    A component with a plain `files` map is the same everywhere and is returned
    as-is; one with `files_by_platform` gets the entry for this OS and
    architecture, or nothing, which reads as "not installable here" rather than
    silently installing the wrong binary.
    """
    by_platform = raw.get("files_by_platform")
    if not by_platform:
        return raw.get("files") or {}
    return by_platform.get(_platform_key()) or {}


def load(repo_root: Path) -> list[Component]:
    """Every component Marvi knows how to install."""
    components = _voice_components(repo_root)
    path = repo_root / "config" / "components.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        log.warning("could not read components.json: %s", exc)
        return components
    for raw in manifest.get("components", []):
        try:
            # Every component carries its own revision now. The one that did
            # not was the VibeVoice speaker voices, which were a pinned git
            # subdirectory checkout and are gone: Kokoro's voices are inside
            # the checkpoint, so there is no second thing to pin.
            components.append(_component_from(raw))
        except (KeyError, TypeError) as exc:
            # One malformed entry must not hide the rest of the catalog.
            log.warning("skipping a malformed component entry: %s", exc)
    return components


def get(repo_root: Path, name: str) -> Component | None:
    return next((c for c in load(repo_root) if c.name == name), None)


def for_capability(repo_root: Path, capability: str) -> list[Component]:
    return [c for c in load(repo_root) if capability in c.needed_for]


def essential(repo_root: Path) -> list[Component]:
    """What the installer puts in place without asking."""
    return [c for c in load(repo_root) if c.essential]


def voice_model_names(repo_root: Path) -> dict[str, str]:
    """The STT and TTS model names, for display.

    Read from the same manifest the installers use, so the Voice page names the
    model that is actually installed rather than a second copy of the string
    that can drift from it.
    """
    try:
        manifest = json.loads(
            (repo_root / "config" / "voice-models.json").read_text(encoding="utf-8")
        )
    except (OSError, ValueError):
        return {}
    names: dict[str, str] = {}
    for job in ("stt", "tts"):
        entry = manifest.get(job)
        if isinstance(entry, str):
            names[job] = entry
        elif isinstance(entry, dict):
            names[job] = str(entry.get("id") or "")
    return names
