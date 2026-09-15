<!--
name: "Tool: file_checkpoints"
description: "List the copies kept before Marvi's file tools changed a file."
-->
List the copies Marvi kept of files just before file_write, file_edit, file_delete or
file_restore changed them, newest first. Read it before file_restore, and when the user
asks what you changed or whether something can be put back. Only Marvi's own file tools
make checkpoints: a change made by a terminal command, another program or the user has
none, so an empty list means "no copy", not "nothing changed".
