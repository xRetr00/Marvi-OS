<!--
name: "Tool: file_restore"
description: "Put a file, or the whole workspace, back the way it was."
-->
Put something back the way it was before Marvi changed it. Marvi keeps two kinds of
copy: one file, taken before file_write, file_edit or file_delete touched it, and the
whole workspace, taken before a terminal command that could lose work. Read
file_checkpoints first and name the checkpoint you are restoring; with a workspace
snapshot id and no path, the whole tree goes back, which is the big hammer -- say what it
will change before you use it. The current state is itself snapshotted first, so a wrong
restore can be undone the same way. Only on an explicit request.
