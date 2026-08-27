# How hermes handles skills, and what Marvi is missing

*A review, written after reading `D:\hermes-agent`. Marvi already took one
piece of this — the after-turn skill proposal in `learning.py`. That was the
smallest piece. This is the rest of it.*

## The shape of the difference

Marvi's skills are a **catalog**: a folder of `SKILL.md`, a name-and-description
line each in the prompt, `skill_read` to load one, an install screen with a
review. That is stages one and two of progressive disclosure and it is correct
as far as it goes.

Hermes treats skills as a **lifecycle**. A skill is discovered, scanned,
installed, invoked, measured, patched, consolidated, and eventually archived —
with a different piece of code owning each step and a different safety rule at
each boundary. Roughly 8,000 lines across fifteen modules, and the interesting
part is not the volume, it is that every one of those steps corresponds to a
way the naive version fails.

| | Marvi | hermes |
|---|---|---|
| On disk | `skills/<name>/SKILL.md` | the same, plus categories with `DESCRIPTION.md`, `references/`, `templates/`, `scripts/`, `assets/` |
| In the prompt | every skill's name + description | category descriptions; skill descriptions capped at 60 chars |
| Loading | `skill_read` tool | `/skill-name`, bundles, `-s` preload, and the tool |
| Gating | none | `platforms:`, environment, config-var presence |
| Where it can come from | one configured store | official, GitHub taps (Anthropic, OpenAI), lobehub, org mirrors |
| Before installing | body shown, warnings, tool intersection | the same, **plus a static security scan and a trust tier** |
| While running | — | usage counters, `last_used_at` |
| After | proposal after a turn *(Marvi has this)* | that, plus a periodic Curator |
| Retirement | manual removal | active → stale → archived, automatic, **never deleted** |

## The seven ideas worth taking

Ordered by what they would fix here, not by how hermes ranks them.

### 1. Skills are not measured, so nothing can be retired

Marvi has no idea which skills are used. `skill_read` is a tool call that
returns a body and forgets it happened. Hermes keeps a sidecar
(`~/.hermes/skills/.usage.json`, deliberately **not** frontmatter, so
operational telemetry never conflicts with a bundled skill's content) holding
`use_count` and `last_used_at` per skill, bumped from the tools that load them.

Everything below depends on this. Without it, "which of these eleven skills has
Marvi ever actually used?" has no answer, and every later decision is a guess.

It is about ten lines and one JSON file.

### 2. A lifecycle, where the terminal state is not deletion

```
active  → default
stale   → unused for stale_after_days
archived→ unused for archive_after_days; moved to .archive/
pinned  → opt out of all of it (orthogonal flag)
```

Two rules in it are the ones worth copying verbatim:

* **Never auto-delete, only archive.** Archive is recoverable, `hermes curator
  restore` brings it back. Marvi's `learning.py` already refuses to write
  without a person; the same asymmetry should hold on the way out.
* **Only agent-created skills are touched.** A skill the user wrote belongs to
  the user, and hermes tracks write *provenance* through a ContextVar
  (`skill_provenance.py`) to tell "the background fork wrote this" from "the
  user asked the foreground agent to write this" — the same file, the same
  tool, different owner.

Marvi's dreamer now holds exactly this invariant over memory: it may withdraw
its own conclusions and nothing else. The skills side has no equivalent yet.

### 3. The Curator: a periodic pass, not only a per-turn one

`learning.py` fires after a turn and asks "did this teach something?". Hermes
has that *and* a Curator that runs when the machine is idle and the last run
was over `interval_hours` ago (default 7 days). It:

- applies the automatic lifecycle transitions above;
- spawns a background review that can **pin / archive / consolidate / patch**;
- writes a run report to disk that a person can read afterwards.

The per-turn pass sees one exchange. The Curator sees the collection — and
consolidation, "these four skills are one skill", is only visible from there.

This is the same relationship Marvi now has between `remembering.py` (per turn)
and `dreaming.py` (periodic, reads across). The skills side has the first half
only.

### 4. Nothing scans an installed skill

`skills_guard.py` statically scans every externally-sourced skill for
exfiltration, prompt injection, destructive commands and persistence, then
applies a **trust tier**:

- `builtin` — ships with hermes, never scanned;
- `trusted` — `openai/skills` and `anthropics/skills` only; "caution" findings
  allowed through;
- `community` — everything else; **any** finding blocks unless forced.

Marvi's install screen shows the body and warns about requested tools, which
puts the whole judgement on a person reading a wall of markdown. A skill is
instructions Marvi will follow later; the injection surface is real, and
"you were shown it" is not a control.

The trust tiering matters as much as the scanner. Treating a first-party
Anthropic skill and a random gist identically means either the bar is too low
for one or too high for the other.

### 5. Skills declare when they apply

Frontmatter carries `platforms:`, environment conditions, and required config
variables; `skill_matches_platform` / `skill_matches_environment` /
`extract_skill_config_vars` resolve them at scan time. A skill that needs
`openhue` configured does not advertise itself on a machine where it is not.

Marvi advertises all eleven skills to every turn regardless. On voice that is
not just tokens, it is latency on every single turn — the exact cost
`advertise()`'s own docstring names.

### 6. Two-level disclosure, not one

Hermes puts **category** `DESCRIPTION.md` in the prompt and the individual
skill descriptions behind that, capped at 60 characters
(`SKILL_PROMPT_DESC_LIMIT`, enforced by a linter). Marvi puts every skill's
full description in the prompt.

At eleven skills that is fine. It is the thing that stops being fine first, and
the fix is structural rather than a trim.

### 7. A linter for skills, advisory by design

`skill_linter.py` checks name-matches-directory, description length, missing
metadata, dangling `references/` links, marketing language, POSIX primitives in
a skill not gated to POSIX, and — the clever one — **prose that names a shell
utility Marvi already has a real tool for**, because naming `grep` in a skill
body steers the model into a raw shell call instead of `file_search`.

Its design contract is the part to copy: findings are **advisory**, surfaced as
guidance on the create path, never a hard reject. The hard rejects live
separately in the validator. Marvi's `review()` produces warnings already and
is the natural place for this.

## Three things hermes does that Marvi should not copy

**Inline shell in `SKILL.md`.** `` !`date +%Y-%m-%d` `` is executed at load
time and its stdout is spliced into the body. It is off by default and it is
still arbitrary code execution triggered by loading a document, one config flag
from being on. Marvi has `${...}` substitution needs at most.

**Bundles.** `/backend-dev` loading four skills at once is a good CLI idea and a
bad voice idea: nobody types slash commands at a microphone, and four bodies is
four times the latency.

**The scaffolding-extraction problem.** Hermes expands `/skill` into a large
model-facing message and then has to *recover* the user's actual instruction
from it, so memory providers don't store the entire skill body as the user's
turn — with byte-identical marker strings shared between the builder and the
extractor, pinned by a test. It is careful work solving a problem created by
the design. Marvi loads skills through a tool result, which never enters the
user turn, and should keep it that way.

Worth noting anyway: **if Marvi ever inlines a skill body into a user turn, her
after-turn worker will start memorising skill bodies as things the user said.**

## Order

1. **Usage counters.** Ten lines, one sidecar file, and everything else is
   guesswork without it.
2. **Lifecycle states with archive-not-delete**, agent-created only.
3. **A scanner and trust tiers** on the install path. This is the security one.
4. **Conditions in frontmatter** — platform and config gating — which is also
   the cheapest win on voice latency.
5. **A Curator pass**, once there is usage data for it to read.
6. Two-level disclosure and the linter, when the count grows enough to need
   them.

The first four are each small. It is the fifth that turns a folder into a
collection that maintains itself, and it cannot be built first.
