# The prompt registry

Every instruction Marvi sends to a model is a file in `prompts/`, loaded by
`marvi_gateway.prompts`. This document says why, and what is still owed.

## The problem it solves

Marvi had nineteen prompt-sized string constants spread across seventeen
modules — about twenty-one thousand characters of instruction with no index.

The cost was never duplication. It was that **nobody could find them.**

`deliberate.SYSTEM_PROMPT` contained the sentence "Silence is the normal,
correct answer. Set worth_it false unless a person would genuinely want
interrupting for this." `config/personas/default.md` contained "Judgement, not
silence by default … and often it is." Both were true, both were shipped, and
the one in the Python file won every time — because task text is more specific
than character text and arrives after it. Picking "Marvi, warm and forward" in
the settings changed how a sentence was worded and nothing about whether one
was said at all.

That contradiction survived for months. Not because it was subtle, but because
there was no list of the places a prompt could be, so nobody looking at
personas had any reason to open `deliberate.py`.

## The structure, and where it comes from

Taken from Claude Code, by way of
[Piebald-AI/claude-code-system-prompts](https://github.com/Piebald-AI/claude-code-system-prompts),
which extracts its prompts from the shipped build. Claude Code has **515 named
prompt strings** rather than one; each is separately addressable, described,
version-stamped and token-counted, and assembled conditionally at runtime. The
scale is different from Marvi's; the problem is identical, and it is worth
copying a solution that already survived 283 releases.

Their file convention, which is the one used here:

```markdown
<!--
name: "System Prompt: Voice assistant"
description: "What this prompt is for and when it is used."
variables:
  - "LANGUAGE"
-->
The body, which is what the model sees.
${LANGUAGE}
```

An HTML comment, so the metadata never reaches the model and the file still
renders as Markdown anywhere.

Three properties, and each is a bug that has actually happened here:

- **Named.** `prompts.catalogue()` lists every prompt with its size. Nobody
  greps for a half-remembered sentence again.
- **Declared variables.** A prompt states what it interpolates. A missing value
  raises rather than shipping the literal text `${STANCE}` to a model, which
  reads to it as an instruction it cannot follow.
- **Measured.** Sizes are reported, so growth is visible. The Agent's
  instruction block reached seventeen thousand characters without anyone
  deciding it should.

Only `${NAME}` is substituted — deliberately not `string.Template`, whose `$$`
means a literal dollar. The chat prompt tells the model to write maths as
`$...$ or $$...$$`, and Template silently collapsed that to `$...$ or $...$`,
the instruction losing the half it existed to give.

## What is not in here

**Character.** How Marvi talks is `config/personas/`, and the split is the
point: a persona is a choice the user makes from a picker, a prompt is the job
being done. `prompts/mind-deliberation.md` describes the decision and takes the
stance as a `${STANCE}` variable; the stance itself comes from the chosen
persona. That is the fix for the contradiction above, expressed structurally
rather than by remembering.

**Skills.** `skills/` follows the Agent Skills specification and is loaded on
demand, per turn. A prompt is always sent; a skill is fetched when relevant.

## No voice-assistant prompt exists upstream

Worth stating plainly, because it was the first thing checked: Claude Code has
none. All 705 extracted files are a coding agent, and the six that mention
"voice" mean tone. `prompts/voice-assistant.md` is written for Marvi.

What it borrows is shape, not content — small single-purpose sections, and the
habits from Claude Code's own behavioural pieces that apply to any agent:
report outcomes faithfully, confirm before irreversible actions, do not narrate
internal deliberation, do not over-correct. What it adds is everything about
being *heard*: nothing visual survives, one thought per turn, numbers said the
way people say them, no error text read aloud, and "I don't know" as a complete
answer.

`voice-assistant.md` is **written and registered but not yet wired.** The
Agent still assembles its instructions inline in `session.py`, and that block
carries behaviour measured turn by turn over several sessions — the memory
recitation rule, the language lock, the reply rule. Swapping it is a change
that deserves its own pass with the Agent suite as the check, not a side effect
of building the registry.

## The coding agent

`prompts/coding-agent.md` goes out with every job `delegate.py` hands to the
Claude Code or Codex CLI. It exists now because those runs were bad without it
— the task crossed on its own, one or two sentences transcribed from speech,
and the agent inferred the rest badly: reports came back as bullet lists of
file paths, which cannot be read aloud, and `investigate` runs proposed changes
nobody had asked for.

It is written to be the sub-agent's system prompt unchanged, once Marvi has her
own coding sub-agent and stops shelling out. Nothing in it depends on which CLI
is on the other end.

## What is still owed

Sixteen constants in the Gateway and two in the Agent have not moved. They are
listed in `STILL_IN_CODE` in `services/gateway/tests/test_prompts.py`, and two
tests hold the line:

- a **new** prompt constant in code fails the suite, so the problem stops
  growing;
- a constant that has moved must leave the list, so the list cannot go stale.

The list is allowed to get shorter and never longer.

## How tools reach the model

Reviewed against Claude Code, because the shapes differ and the difference is
the largest single cost in a Marvi request.

### Claude Code: two tiers

Core tools — Read, Edit, Bash, Grep, Glob and a handful more — carry full
JSONSchema at the top of the prompt. **Everything else is deferred: the name
appears in a `<system-reminder>` list and the schema does not.** Calling a
deferred tool without fetching it fails with `InputValidationError`. `ToolSearch`
loads schemas on demand, by exact name (`select:Read,Edit`) or by keyword.

Three details worth copying:

- The deferred **names are always visible.** A model cannot decide to look up a
  thing whose existence it has no reason to suspect.
- The failure mode is **named and explained** in the tool's own description, so
  a model that calls a deferred tool knows what happened and what to do.
- MCP servers still connecting get their own reminder saying *do not report the
  capability as unavailable while they are connecting.*

### Marvi: everything, every turn

All 61 tools ship with full schemas on every request. Deferral exists —
`MARVI_DEFER_TOOLS`, `MARVI_CORE_TOOLS`, `tool_search`, and a seven-tool
`DEFAULT_CORE` — and is **off by default**, because it was measured and
reverted. Over 123 real turns with it on: seven distinct tools called,
`tool_search` called once, and twenty-three flat refusals of things Marvi can
do — "I can't open websites in a browser right now", "I don't have access to
your calendar" — each phrased as a fact about herself, none true.

That failure has since been fixed, and the fix has not been re-measured
against deferral. `catalogue_index()` now puts **every tool name** in the
instructions, grouped by area, schemas excluded. That is exactly the missing
piece: names are what turn "I can't" into knowing there is something to look
up. Marvi now has both halves of Claude Code's arrangement and has never run
them together.

### What it costs today

Measured on the current tree, counting name, description and a modest
per-argument schema:

| | chars | ~tokens |
|---|---|---|
| every schema, every turn (today) | 23,251 | 5,812 |
| core schemas + all 61 names | 3,936 | 984 |
| **difference** | **19,315** | **4,828 per turn** |

Rewriting the descriptions from a 38-character median to 245 was the right
call — `send_email` saying "Send an email" is why a model has to guess whether
an action can be undone — but it is not free. Descriptions went from 4,678 to
15,267 characters, about **2,647 extra tokens on every request** for as long as
deferral stays off.

### The recommendation

Run the experiment that has never been run: `MARVI_DEFER_TOOLS=on` **with**
`catalogue_index()` supplying the names. The old measurement condemned
deferral-without-names, which is a different thing. Watch the number that
failed before — refusals of capabilities Marvi has — not the token count, which
will obviously improve.

If it fails again, the fallback is not "send everything": it is to widen
`DEFAULT_CORE` beyond seven, since the reverting measurement also showed the
loaded case reaching eighteen distinct tools at 0.1s median latency.

## Measured: 60 real turns with deferral on

The recommendation above said to run the experiment that had never been run.
It has now been run, against `inclusionai/ling-3.0-flash`, five questions taken
from the twenty-three refusals in the log, six samples each, two conditions
differing only in the prompt.

| condition | denied a real capability |
|---|---|
| A — the note in force when deferral was measured and reverted | **8/30 (27%)** |
| B — `prompts/deferred-tools.md` | **0/30 (0%)** |

Fisher exact, one-sided: **p = 0.0023.** The same question, the same tools:

    A   "I don't have a tool to open a website in a browser directly."
    B   "Yes, I can open a website in a browser for you. Which website?"

So the refusals are fixed, and the cause was what the earlier note failed to
say — not that more tools exist, but that *you may not claim one is missing
without looking.*

### And a second finding, which is a problem

Given imperative asks ("open github.com in the browser"), the model called the
deferred tool **directly, 24 times out of 24** — `browser_open`,
`calendar_events`, `read_screen`, `schedule_add` — none of whose schemas were
in the request. It never once called `tool_search`.

Strengthening the wording did not help. A second run after adding *"Their
schemas are NOT loaded. Calling one of the names below directly will fail"* and
*"Never emit a call for a name you have only read in the list"* was again
**24/24 calling directly**.

**A name the model can see is a name it will call.** That is not something a
prompt can talk it out of, and it is worth stating plainly because the obvious
response — write the rule more forcefully — was tried and measured and did not
work.

Claude Code lives with this: its `ToolSearch` description names the failure
(`InputValidationError`) so the model can recover from it, rather than trying
to prevent it.

**Marvi can do better than recover, because Marvi is not shaped like Claude
Code here.** The Gateway registers all 61 tools; only the Agent's function list
is filtered. A call for a deferred tool is a call the Gateway could simply
serve. And the arguments the model guesses from the name and the listed
description are mostly right — checked against the real schemas:

    18/23  guessed arguments valid
     3/23  wrong (a missing or extra field)
     2/23  a name that does not exist

Seventy-eight percent first time, and the other twenty-two percent now get the
Gateway's own 422, which says which argument and that calling it again
unchanged will fail the same way.

That points at lazy loading rather than search-then-call: let the name be the
index, resolve an unloaded name against the full catalogue, and run it. It is a
change to the Agent's dispatch, not to a prompt, and it is not made here.

## Lazy tool loading

Built, tested, and **off by default.** One word turns it on:
`MARVI_DEFER_TOOLS=lazy`.

### What it does

Every tool is in the request and every one is callable. The core set carries
its full schema; the rest carry **the first sentence of their description and
an open arguments object.** The model calls by name — which is what it does
anyway — the Gateway checks the arguments, and the first call to a tool swaps
in its exact schema for the rest of the session.

### Why, in one line from the codebase

`from_gateway` already recorded the failure this fixes:

> she stopped refusing and started calling them by name, directly, the way a
> model does with any tool it can see — and LiveKit answered `unknown AI
> function` ten times, because a named tool with no schema loaded is not
> callable.

Deferring makes the model reach for names it cannot call. Loading everything
makes every turn carry 6,800 tokens of schema. Lazy is the third option: the
name is callable, the schema is what waits.

### Cost

| | chars | ~tokens |
|---|---|---|
| everything, full schemas (today) | 27,196 | 6,799 |
| **core full + rest brief (lazy)** | **8,662** | **2,165** |
| core full + names in the prompt (defer) | 4,236 | 1,059 |

**68% off the tool payload**, and no round trip.

### Measured

Thirty-two calls, five imperative asks, `inclusionai/ling-3.0-flash`, arguments
checked against the real registry schemas:

| | |
|---|---|
| call valid first time | **24/32 (75%)** |
| needs a 422, which names the argument | 6/32 (19%) |
| answered without calling | 2/32 (6%) |
| **refused a capability** | **0** |
| **`unknown AI function`** | **0** |

The 422 path is not a failure mode: the refusal says which argument and what it
expects, and promotion means the retry uses the exact schema. A tool is
imprecise once.

Tuning happens in the first sentence, which is what a brief tool is called
from. `cronjob` failed until its opening line named the argument that decides
the call — "Manage scheduled jobs: pass action as one of create, list, edit…"
rather than "Create, inspect, edit, run, pause, resume or remove scheduled
jobs."

### Why it is not the default

The current default was chosen after three sweeps of the same 123 real turns.
This is thirty-two offline calls. Flipping a measured default on the smaller
number is the mistake this file already documents once, and it is not repeated
here.
