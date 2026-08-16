# Delivery Phase Index

Each phase file is a durable checkpoint. Update its status, evidence, decisions,
and commit list in the same change as the implementation it tracks. A phase may
start early when it removes risk for another phase; dependencies and remaining
gates still apply.

| Phase | File | Status |
|---:|---|---|
| 0 | [`00-foundations-hardware.md`](00-foundations-hardware.md) | in progress |
| 1 | [`01-gateway-livekit.md`](01-gateway-livekit.md) | scaffolded |
| 2 | [`02-desktop-island.md`](02-desktop-island.md) | complete |
| 3 | [`03-full-duplex-voice.md`](03-full-duplex-voice.md) | in progress |
| 4 | [`04-tools-room.md`](04-tools-room.md) | complete |
| 5 | [`05-world-memory.md`](05-world-memory.md) | complete |
| 6 | [`06-vision-proactive.md`](06-vision-proactive.md) | planned |
| 7 | [`07-delegation-release.md`](07-delegation-release.md) | planned |

Status vocabulary: `planned`, `scaffolded`, `in progress`, `blocked`, and
`complete`. Only mark a phase complete when every acceptance gate has named
evidence.
