<!--
name: "Tool: process_output (coding)"
description: "Read what a background command has printed so far."
-->
Reads what a command started with `terminal_run` and `background: true` has
printed so far, and whether it has finished.

- `pid` is the one `terminal_run` returned when it started the command.
- Do not call this in a loop waiting for a command to end. Start the long thing,
  do other useful work, then read it once. A job spent polling is a job that did
  nothing else.
- When it has finished, read the exit code and the tally the tool printed, not a
  line that merely looks like success.
