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
