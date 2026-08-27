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
| 6 | [`06-proactive-mind.md`](06-proactive-mind.md) | complete |
| 7 | [`07-release.md`](07-release.md) | in progress |
| 8 | [`08-vision.md`](08-vision.md) | complete |
| 9 | [`09-providers-identity.md`](09-providers-identity.md) | feature-complete |
| 10 | [`10-resilience.md`](10-resilience.md) | complete |
| 11 | [`11-setup.md`](11-setup.md) | complete |
| 12 | [`12-pet-companion.md`](12-pet-companion.md) | in progress |
| 13 | [`13-cron-jobs.md`](13-cron-jobs.md) | complete |
| 14 | [`14-messaging-companion.md`](14-messaging-companion.md) | complete |
| 15 | [`15-standalone-messaging-runtime.md`](15-standalone-messaging-runtime.md) | complete |

Status vocabulary: `planned`, `scaffolded`, `in progress`, `blocked`, and
`complete`. Only mark a phase complete when every acceptance gate has named
evidence.
