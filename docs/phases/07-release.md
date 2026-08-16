# Phase 7 — First Windows Release

**Status:** in progress
**Depends on:** Phases 2 and 6

## Scope

- Extract and adapt the tested Marvi/Hermes Windows update handoff.
- Test updates from multiple older releases and from interrupted updates.
- Package and publish the first Windows release of Marvi OS.

## Removed from scope

The durable job bridge to Marvi Agent for coding, research, and long-running
work is **dropped**, by decision on 2026-08-16. Marvi OS is an ambient voice and
vision assistant; delegating deep work to a separate coding agent is a different
product. ADR-001 already keeps the two runtimes independent, and nothing in the
shipped surface depends on the bridge.

## Acceptance evidence required

- An update applied from an older release, not only from the current checkout.
- An interrupted update leaves the previous installation working.
- A packaged build starts, reaches the tray, and reports its version, commit,
  and channel in About.
