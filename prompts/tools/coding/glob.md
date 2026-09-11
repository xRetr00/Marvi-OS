<!--
name: "Tool: glob (coding)"
description: "Find files by name pattern. Ported from Claude Code's Glob tool."
-->
Fast file pattern matching, for any size of codebase.

- `pattern` is a glob: `**/*.js`, `src/**/*.ts`, `tests/test_*.py`.
- Results come back sorted by when they were last changed, newest first.
- Use it whenever you need files by name. When you are looking for something by
  what it *contains*, that is `grep`.
- Several searches that might each be useful can go out together in one round.
