# Identity — `SOUL.md` and `USER.md`

Two files, both in the prompt on every turn, filled by opposite means.

| | `SOUL.md` | `USER.md` |
|---|---|---|
| Who it describes | Marvi | you |
| Who writes it | shipped with Marvi; yours to edit | Marvi, by listening |
| Does Marvi write it | **never** | yes, and you can override any of it |

## `SOUL.md`

Ships at `config/SOUL.md` and is copied into `%LOCALAPPDATA%\Marvi OS` on first
run. **Seeded once and never overwritten** — an update that silently replaced
your edited soul would be the worst possible behaviour for a file describing who
Marvi is.

Marvi does not write this file, ever. A persona that edits itself is one nobody
can audit, and the whole point of a soul is that it is stable.

It covers four things: how Marvi talks, when it speaks first, what it does
before acting, and what it never does. The last section — that content from an
email or a page or a camera is information and never instruction — is the one
that must survive truncation, which is why the budget is sized with headroom
rather than trimmed to fit exactly.

Edit it on the Identity page. It is yours.

## `USER.md`

Starts as a template of "not known yet" and fills in as Marvi learns. Two
mechanisms, deliberately different:

### Noticing — always on, free

Most of what lands here is volunteered. "I'm a software engineer", "call me
Shereef", "I'm usually asleep by one" — said in passing, none of it in answer to
a question. Marvi records it and does not make a moment of it.

The plainest phrasings are caught by pattern rather than by a model call, so
"I'm Shereef" works even when the provider is having a bad day.

### Asking — rationed hard

Occasionally something matters enough to ask for, and the name is the obvious
case: without it Marvi cannot address anyone.

The failure mode here is not "Marvi learns slowly". It is **Marvi becomes an
interrogation** and gets switched off. So the limits live in code, not in the
prompt — a model told to "ask occasionally, don't be annoying" is fine for a
while and then has a chatty afternoon, because annoyance is cumulative and the
model cannot feel it:

- nothing in the first two exchanges of a conversation;
- one question at most, then a **20-hour cooldown**;
- never the same gap twice;
- **declining is permanent.** Deflect once and Marvi never raises it again, in
  any wording.

The cooldown starts when the question is *offered*, not when Marvi is detected
to have asked it. Detecting that is guesswork, and guessing wrong means asking
again next turn — the exact behaviour this is designed to prevent. Burning an
unused window is harmless: the gap stays open and comes round again.

The model still decides whether the moment suits and how to phrase it. It does
not decide how often.

### What Marvi owns, and what it does not

Marvi owns its own headings — Name, How to address them, Work, Hours and
rhythm, Standing preferences — and regenerates them, so the file cannot drift
into a pile of contradicting notes. **Anything you write under your own heading
is kept verbatim.**

Recording needs no confirmation: it is Marvi keeping notes, not acting on your
behalf. Everything is visible and editable on the Identity page, and clearing a
field makes it askable again.

## The budget

Both files are trimmed to fit `MARVI_IDENTITY_BUDGET` (1200 tokens by default,
45% to the soul). Every token here is paid on **every turn**, including the
latency-critical voice path.

1200 sounds like a lot to pay each time, but this is the byte-identical prefix —
it is the part that caches, so the marginal cost after the first turn is close
to nothing. That is also why identity leads the prompt rather than trailing it.

Truncation is line-based and the Identity page says when it has happened.
