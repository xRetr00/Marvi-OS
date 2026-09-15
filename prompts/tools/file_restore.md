<!--
name: "Tool: file_restore"
description: "Put a file back the way it was before Marvi changed it."
-->
Put a file back the way it was before one of Marvi's file tools changed or deleted it.
Without a checkpoint id it restores the newest copy of that file; read file_checkpoints
first when there may be several and name the one you are restoring. The current version
is itself checkpointed before it is replaced, so a wrong restore can be undone the same
way. Only on an explicit request -- restoring overwrites whatever the file says now.
