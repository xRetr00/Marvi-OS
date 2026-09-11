<!--
name: "Tool: process_output"
description: "Read what a background terminal_run command has printed since the last read."
-->
Read what a background command started with terminal_run has printed since you last
asked, and whether it is still running and its exit code once it has finished. Each read
returns only new output, so an empty answer on a running command means it has said
nothing new -- not that it failed. Do not sit calling this in a tight loop: do other
useful work, then look. Stop a command with process_stop.
