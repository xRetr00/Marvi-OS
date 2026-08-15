# Target Environment

Detected on 2026-08-16. Re-run and update this document before interpreting
benchmark results on a different machine.

## Hardware

| Component | Detected |
|---|---|
| GPU | NVIDIA GeForce RTX 3060 |
| VRAM | 12,288 MiB |
| NVIDIA driver | 610.88 |
| Operating system | Windows, native runtime required |

## Development toolchain

| Tool | Detected |
|---|---|
| Python | 3.12.0 |
| Node.js | 24.12.0 |
| Rust | rustc/cargo 1.94.1 |
| uv | 0.11.3 |
| CMake | 4.2.1 |
| LiveKit CLI (`lk`) | 2.18.2 (development tooling only) |
| MSVC `cl` in current shell | not detected |
| LiveKit docs MCP | unavailable in current Codex session |

## Before LiveKit implementation

1. Use `lk` only for development, documentation, and local diagnostics. It is
   not packaged as a Marvi OS command or exposed to users.
2. Configure the LiveKit documentation MCP server, or verify every API against
   current official web documentation before use.
3. Run native compiler work from a Visual Studio Developer shell or configure
   the required MSVC build tools.
4. Capture CUDA toolkit/runtime versions used by each voice candidate.
5. Do not share a Python environment between Gateway, Kyutai/VibeVoice, and optional
   alternate STT engines; use pinned `uv` projects/processes.

The installed development binary is currently at
`C:\Users\xRetro\AppData\Local\Microsoft\WinGet\Packages\LiveKit.LiveKitCLI_Microsoft.Winget.Source_8wekyb3d8bbwe\lk.exe`.
Its directory was added to the user PATH for future shells.

Toolchain presence does not prove model compatibility. The benchmark must record
actual model load, warmup, inference, and teardown results.
