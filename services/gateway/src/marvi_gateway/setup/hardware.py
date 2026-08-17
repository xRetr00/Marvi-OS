"""What this machine can actually run on.

The mistake this exists to prevent: installing a CPU build of PyTorch on a
machine with a perfectly good GPU, then wondering why the voice model is slow.
It is silent, it is easy, and it costs a multi-gigabyte reinstall to undo. So
**every** path that installs or updates something GPU-capable asks first.

Detection is deliberately layered from cheapest to most reliable:

1. `torch.cuda` if torch is already importable — the ground truth, since it is
   the thing that will actually run.
2. `nvidia-smi`, which exists whenever an NVIDIA driver does, without needing
   torch installed yet. This is the case that matters during a first install.
3. Windows' own device list, which sees the card even with no driver tooling —
   enough to say "you have a GPU but no driver", which is a different problem
   with a different fix.

Nothing here guesses on the user's behalf. It reports, and the caller asks.
"""

from __future__ import annotations

import os
import shutil
import subprocess
from dataclasses import dataclass, field
from typing import Any

from ..logs import get_logger

log = get_logger("setup")

PROBE_TIMEOUT = 8.0

#: Set to `1`/`0` to skip the question entirely — for CI and for anyone who has
#: already made the decision and does not want asking again.
PREFERENCE_ENV = "MARVI_USE_GPU"


@dataclass
class Gpu:
    vendor: str
    name: str
    memory_mb: int = 0
    driver: str = ""
    #: CUDA/ROCm actually usable right now, not merely a card being present.
    usable: bool = False
    detail: str = ""

    def as_dict(self) -> dict[str, Any]:
        return {
            "vendor": self.vendor,
            "name": self.name,
            "memory_mb": self.memory_mb,
            "driver": self.driver,
            "usable": self.usable,
            "detail": self.detail,
        }


@dataclass
class Hardware:
    gpus: list[Gpu] = field(default_factory=list)
    detail: str = ""

    @property
    def has_usable_gpu(self) -> bool:
        return any(gpu.usable for gpu in self.gpus)

    @property
    def has_gpu_hardware(self) -> bool:
        return bool(self.gpus)

    def best(self) -> Gpu | None:
        usable = [g for g in self.gpus if g.usable] or self.gpus
        return max(usable, key=lambda g: g.memory_mb, default=None)

    def as_dict(self) -> dict[str, Any]:
        return {
            "gpus": [gpu.as_dict() for gpu in self.gpus],
            "has_usable_gpu": self.has_usable_gpu,
            "has_gpu_hardware": self.has_gpu_hardware,
            "detail": self.detail,
        }


def _run(command: list[str]) -> str:
    try:
        finished = subprocess.run(  # noqa: S603 - fixed argv, no shell
            command, capture_output=True, text=True, timeout=PROBE_TIMEOUT
        )
    except (OSError, subprocess.TimeoutExpired):
        return ""
    return finished.stdout if finished.returncode == 0 else ""


def _from_torch() -> list[Gpu]:
    """Ground truth, when torch is already here."""
    try:
        import torch  # noqa: PLC0415 - optional and slow; only import if present
    except Exception:
        return []
    try:
        if not torch.cuda.is_available():
            # Torch is installed but cannot see a GPU. That is exactly the
            # wrong-build case, and worth saying so rather than reporting none.
            built = getattr(torch.version, "cuda", None)
            if not built:
                return [
                    Gpu(
                        vendor="unknown",
                        name="torch is a CPU-only build",
                        usable=False,
                        detail="Reinstall torch with CUDA to use a GPU.",
                    )
                ]
            return []
        found = []
        for index in range(torch.cuda.device_count()):
            properties = torch.cuda.get_device_properties(index)
            found.append(
                Gpu(
                    vendor="nvidia",
                    name=properties.name,
                    memory_mb=int(properties.total_memory / 1024**2),
                    driver=str(getattr(torch.version, "cuda", "")),
                    usable=True,
                    detail="torch reports CUDA available",
                )
            )
        return found
    except Exception as exc:
        log.debug("torch probe failed: %s", exc)
        return []


def _from_nvidia_smi() -> list[Gpu]:
    """Works before torch exists, which is when a first install needs it."""
    if not shutil.which("nvidia-smi"):
        return []
    output = _run(
        [
            "nvidia-smi",
            "--query-gpu=name,memory.total,driver_version",
            "--format=csv,noheader,nounits",
        ]
    )
    found = []
    for line in output.splitlines():
        parts = [part.strip() for part in line.split(",")]
        if len(parts) < 2:
            continue
        try:
            memory = int(float(parts[1]))
        except ValueError:
            memory = 0
        found.append(
            Gpu(
                vendor="nvidia",
                name=parts[0],
                memory_mb=memory,
                driver=parts[2] if len(parts) > 2 else "",
                usable=True,
                detail="nvidia-smi",
            )
        )
    return found


def _from_windows() -> list[Gpu]:
    """Sees the card even with no driver tooling installed."""
    if os.name != "nt":
        return []
    output = _run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "Get-CimInstance Win32_VideoController | "
            "ForEach-Object { \"$($_.Name)|$($_.AdapterRAM)|$($_.DriverVersion)\" }",
        ]
    )
    found = []
    for line in output.splitlines():
        parts = line.strip().split("|")
        if not parts or not parts[0]:
            continue
        name = parts[0]
        lowered = name.lower()
        vendor = (
            "nvidia" if "nvidia" in lowered or "geforce" in lowered or "rtx" in lowered
            else "amd" if "radeon" in lowered or "amd" in lowered
            else "intel" if "intel" in lowered
            else "unknown"
        )
        # Integrated graphics are not what anyone means by "use the GPU" for a
        # speech model, so they are reported but never counted as usable.
        if vendor == "intel":
            continue
        try:
            memory = int(int(parts[1]) / 1024**2) if len(parts) > 1 and parts[1] else 0
        except ValueError:
            memory = 0
        found.append(
            Gpu(
                vendor=vendor,
                name=name,
                memory_mb=memory,
                driver=parts[2] if len(parts) > 2 else "",
                usable=False,
                detail="present, but no working CUDA/ROCm was found",
            )
        )
    return found


def detect() -> Hardware:
    """Look for a GPU, cheapest reliable source first."""
    for probe, label in (
        (_from_torch, "torch"),
        (_from_nvidia_smi, "nvidia-smi"),
        (_from_windows, "device list"),
    ):
        found = probe()
        if found:
            return Hardware(gpus=found, detail=f"detected via {label}")
    return Hardware(detail="no discrete GPU found")


# -- the decision ----------------------------------------------------------------


def preference() -> bool | None:
    """The user's standing answer, or None if they have not been asked."""
    raw = os.environ.get(PREFERENCE_ENV, "").strip().lower()
    if raw in ("1", "true", "yes", "on", "gpu"):
        return True
    if raw in ("0", "false", "no", "off", "cpu"):
        return False
    return None


def remember(use_gpu: bool) -> None:
    """Save the answer so nothing asks again on the next update."""
    from ..providers import config

    config.update({PREFERENCE_ENV: "1" if use_gpu else "0"})
    log.info("recorded GPU preference: %s", "gpu" if use_gpu else "cpu")


def question(hardware: Hardware | None = None) -> dict[str, Any]:
    """What to ask, and whether to ask at all.

    Returns `ask: False` with a decided answer when there is nothing to decide —
    no GPU means CPU, and a saved preference means it was already settled.
    """
    found = hardware or detect()
    saved = preference()
    if saved is not None:
        return {
            "ask": False,
            "use_gpu": saved and found.has_usable_gpu,
            "reason": f"remembered ({PREFERENCE_ENV})",
            "hardware": found.as_dict(),
        }
    if not found.has_gpu_hardware:
        return {
            "ask": False,
            "use_gpu": False,
            "reason": "no discrete GPU on this machine",
            "hardware": found.as_dict(),
        }

    best = found.best()
    if not found.has_usable_gpu:
        # The card is there but nothing can drive it. Asking "GPU or CPU?" would
        # be offering a choice that does not exist; say what is missing instead.
        return {
            "ask": False,
            "use_gpu": False,
            "reason": (
                f"{best.name if best else 'a GPU'} is present but no working "
                "CUDA driver was found; install NVIDIA drivers to use it"
            ),
            "hardware": found.as_dict(),
        }
    memory = f" with {best.memory_mb / 1024:.0f} GB" if best and best.memory_mb else ""
    return {
        "ask": True,
        "use_gpu": True,  # the sensible default when asked
        "prompt": (
            f"Found {best.name if best else 'a GPU'}{memory}. Use it for models "
            "that support it? Choosing CPU installs smaller packages but voice "
            "and vision will be markedly slower."
        ),
        "reason": "a usable GPU is available",
        "hardware": found.as_dict(),
    }


def torch_index(use_gpu: bool) -> str:
    """Which PyTorch index to install from.

    The whole point of this module in one function: a GPU machine that gets the
    CPU wheel is the mistake, and it is invisible until someone wonders why
    everything is slow.
    """
    return "https://download.pytorch.org/whl/cu130" if use_gpu else "https://download.pytorch.org/whl/cpu"
