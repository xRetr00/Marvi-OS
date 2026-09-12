# Storage

What Marvi keeps on disk, what cleans it, and what is still open. Measured on
the development machine on 12 September 2026.

## What cleans what

| Thing | Where it is bounded | Rule |
|---|---|---|
| Logs | `logs.py` (size), `storage.cycle_logs` (age) | 8 MB × 3 per file; every 3 days the previous cycle is deleted and the current one kept as `.1` |
| `audit.jsonl` | `runtime.RuntimeStore.audit` | Room polls (`room_state`, `room_health`) are not audited; past 8 MB the newest 30,000 lines are kept |
| `latency.jsonl` | `latency.record` | Past 4 MB the newest 10,000 lines are kept |
| `state/observations.jsonl` | `observations.prune` | 20,000 rows |
| `resources.jsonl` | `accounting.Accountant._write` | `MOST_KEPT` readings |
| Backups (`*.bak`, `*.before-*`, `*-backup-*`) | `storage.old_backups`; the room plugin's `_backup` | One per thing: a new backup deletes the one before it |
| Visitor photos | Desktop popup | **Seen** deletes them; **See later** asks again in an hour |
| Leftovers from retired engines | `storage._leftover_candidates` | Deleted by the daily pass |
| `%TEMP%\marvi-*` | `storage.old_temporary` | Deleted after a day |
| Speech engines not selected | `marvi storage clean --engines` | Asked, never automatic: each is a download to get back |
| uv and npm caches | The installer, after every install/update; `marvi storage clean --caches` | `uv cache prune`, `npm cache verify` |

The daily pass is `storage.housekeep`, run by the initiative scheduler as the
`storage` job. When a disk crosses the low-space line, `machine` reports it and
`Initiative._make_room` runs the pass at once and adds what it freed, and what
the unused engines hold, to the sentence she says.

`marvi storage` shows sizes; `marvi storage clean` runs the pass now.

## Why the uv cache is not in the daily pass

`uv cache prune` waits for every running uv process to exit. Marvi starts her
Gateway, Agent and sidecars through `uv run`, so while she is up the prune never
starts (checked: it printed "Cache is currently in-use, waiting for other uv
processes to finish" and sat there). The installer runs it instead, because
Marvi is closed during an update. `--force` skips the wait, and is only safe
when nothing is installing at the same time, which a daily timer cannot promise.

## Open: the Python environments and the uv cache

This part is a plan, not a change. Nothing here has been decided.

### What is there

| Environment | torch | Size |
|---|---|---|
| `install/.venv` (Gateway, Agent) | 2.13.0+cu130 | 4.7 GB |
| `services/tts-voxtream/.venv` | 2.5.1+cu121 | 5.2 GB |
| `services/tts-cute/.venv` | 2.5.1+cu121 | 4.6 GB |
| `services/stt-kyutai/.venv` | 2.9.1+cu130 | 2.8 GB |
| `services/tts-ctc/.venv` (retired) | 2.6.0+cu118 | 5.5 GB |

The uv cache was 70.7 GB, 64 GB of it `archive-v0`, and **25 unpacked torch
builds** were in it against the 4 the environments actually use. Every update
that changed a torch pin or the CUDA backend (`UV_TORCH_BACKEND`) added one, and
nothing ever removed the old ones.

### How the bytes are shared

uv installs by **hardlink** on Windows. `torch_cuda.dll` in `tts-voxtream` and in
`tts-cute` is the same file as the one in the cache, three names for one set of
bytes. Consequences:

* Sizes add up to more than the disk actually holds. `marvi storage status` says
  so rather than de-duplicating, which would need a file-ID walk.
* Deleting an environment frees almost nothing on its own; deleting the cache
  entry frees nothing while an environment still links to it. Space comes back
  when **both** are gone, which is why removing an engine and pruning the
  cache go together.
* The cache and the environments must stay on the **same drive**. On different
  drives uv falls back to copying and every byte is stored twice.

### Options to evaluate

1. **One torch for every isolated engine.** VoXtream2 and CuteTTS already share
   one build and so share its bytes. Kyutai is on another, and the Gateway on a
   third. Each engine that can move to the Gateway's build stops costing its own
   ~2.5 GB. Needs each engine's torch pin tested against the newer build
   (`moshi` pinned the older one, which is why Kyutai is isolated at all).
2. **Build an engine's environment only when it is selected**, and offer to
   remove it when another is chosen. The catalog already knows which engine is
   selected (`catalog.ENGINE_COMPONENTS`); the installer would have to follow it.
3. **Prune after every sync, not only at the end of an update.** `_sync_project`
   is where a new torch build arrives; pruning there would remove the build it
   replaced, instead of leaving it until the next update.
4. **Move Marvi to another drive.** `MARVI_HOME` and `UV_CACHE_DIR` together,
   never one without the other (see the drive rule above).
5. **Measure the real footprint**: count bytes by file ID, so the number
   Marvi reports is what deleting would actually free.

Questions to answer before choosing: which engines can share the Gateway's
torch build, and how long a cold rebuild of an engine environment takes on the
target machine (that is what option 2 costs every time the engine is switched).
