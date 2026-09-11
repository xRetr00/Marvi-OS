<!--
name: "Tool: file_edit (coding)"
description: "Change part of a file by exact replacement. Ported from Claude Code's Edit tool."
-->
Performs an exact string replacement in a file.

- You must `file_read` the file in this job before editing it, or the edit is
  refused.
- `old` must match the file exactly, including indentation — tabs and spaces as
  they appear in the file. When you copy from `file_read` output, take only the
  file's text, never a line number in front of it.
- `old` must be unique in the file, or the edit fails. Keep it minimal — usually
  one to three lines, just enough to be unique. When it is not unique, add the
  least extra surrounding context that makes it so.
- `replace_all: true` replaces every occurrence instead — the right tool for
  renaming something across a file.
- Prefer editing an existing file to writing a new one. Never create a file the
  job did not need.
- Do not add emojis to files unless asked.
