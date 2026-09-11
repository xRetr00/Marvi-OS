<!--
name: "Tool: grep (coding)"
description: "Search file contents with a regular expression. Ported from Claude Code's Grep tool."
-->
A content search built on ripgrep. Use it for every search of what files
contain — never `findstr`, `Select-String`, `grep` or `rg` through the shell.

- `pattern` is a regular expression, in ripgrep's syntax: `log.*Error`,
  `function\s+\w+`. Literal braces need escaping — `interface\{\}` to find
  `interface{}`.
- `glob` filters by file name (`*.py`, `*.{ts,tsx}`); `type` filters by language
  (`py`, `js`, `rust`) and is faster where it fits.
- `output_mode` is `files_with_matches` (the default — paths only), `content`
  (the matching lines) or `count` (matches per file). Start with files, then read
  the lines you care about.
- `context`, or `before` and `after`, add lines around each match in `content`
  mode; `case_insensitive` ignores case.
- By default a match is on one line. `multiline` lets a pattern span lines, for
  things like a struct's fields.
- `head_limit` caps the results. A search that returns a great deal is usually a
  search that needs narrowing, not reading.

For an open-ended search that may need several rounds of looking, run the likely
searches together in one round rather than one after another.
