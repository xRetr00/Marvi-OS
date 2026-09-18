<!--
name: "Tool: code_run"
description: "Run a short Python snippet in a scratch directory, under limits."
-->
Run a short Python snippet in an empty directory of its own, with a time limit, a memory
limit and no network. Use it to work something out -- arithmetic over a list, reshaping
data you already have, checking what a library returns -- and print what you want back,
because only stdout and stderr come out. Files it writes live for the length of the call
and are then deleted; anything worth keeping goes to the workspace with file_write.

How confined it is depends on the machine, and the result says which one you got.
`isolation: appcontainer` means Windows itself refuses the snippet every file outside its
scratch directory and drops every connection it tries, so code you have no reason to
trust is safe to run. `isolation: job` means only the time, memory and process limits
apply: the snippet cannot run away with the machine, but it can still read files as the
user, and `isolation_detail` says why the stronger one was unavailable.

Use terminal_run instead when the job genuinely needs the workspace, the network, or the
user's own tools.
