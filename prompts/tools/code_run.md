<!--
name: "Tool: code_run"
description: "Run a short Python snippet in a scratch directory, under limits."
-->
Run a short Python snippet in an empty directory of its own, with a time limit, a memory
limit and no network. Use it to work something out -- arithmetic over a list, reshaping
data you already have, checking what a library returns -- and print what you want back,
because only stdout and stderr come out. Files it writes live for the length of the call
and are then deleted; anything worth keeping goes to the workspace with file_write.

It is a scratch pad, not a safe place for code you do not trust: the limits stop a
snippet running away with the machine, they do not stop a determined one reading files as
the user. Use terminal_run when the job genuinely needs the workspace, the network or the
user's own tools.
