---
name: writing-a-skill
description: How to write a new skill for Marvi, or improve one that exists. Use when the user asks you to remember a procedure, says "do it this way from now on", asks for a new skill, or when you notice you have explained the same multi-step thing more than once.
license: MIT
metadata:
  author: Marvi OS
  version: "1.0"
---

# Writing a skill

A skill is a directory with a `SKILL.md` in it, following the Agent Skills
specification. Marvi implements that format rather than a private one, so a
skill written here works in other agents and one written elsewhere works here.

## Does it need to be a skill?

Stop at the first that fits:

- **True every turn?** It belongs in the system prompt, not a skill. A skill
  that says "use this always" is loaded always, which defeats the point.
- **A fact about the user?** USER.md. See `knowing-the-user`.
- **A fact about the world?** Memory. See `remembering`.
- **A procedure, needed sometimes, easy to get wrong?** That is a skill.

## The file

```
---
name: kebab-case-name
description: What it does, and when to use it.
---

# Instructions
```

`name`: 1–64 characters, lowercase letters, digits and single hyphens, and it
must match the directory name.

`description`: up to 1024 characters, and it is the only part that is always
in the prompt. Write it for the decision it has to support — what the skill
does, *and the situations that should trigger it*, in the words the user would
actually say. "Helps with the room" never fires. "Use when the user asks about
lights, modes, sleep, or the camera" does.

Optional: `license`, `compatibility`, `metadata`, `allowed-tools`. Nothing
else — an unexpected key is a validation error.

## The body

Keep it under 500 lines; well under, if you can. It is loaded whole the moment
the skill is chosen, and every line is paid for from then on.

Write what to do, not why it matters. Steps, the shape of a good answer, and
the mistakes that have actually been made. Concrete beats complete.

Longer reference material goes in `references/`, scripts in `scripts/`,
templates in `assets/` — all loaded only if the instructions send you there.

## `allowed-tools` is a request

It narrows a skill to the tools it says it needs. It never widens anything: a
tool that needs confirmation still needs confirmation, whatever the file says.
A skill cannot grant itself permission by declaring it.

## Where it goes

Marvi's own skills live in `skills/` in her source tree and ship with her.
Installed ones live in the skills directory under her installation, and one
there with the same name wins.

## Test it by the description alone

Read only the `description` and ask: given that sentence, would you know to
open this file at the right moment? If not, fix the description before writing
another word of the body. Everything else is wasted if the skill never fires.
