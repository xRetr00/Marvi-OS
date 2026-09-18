<!--
name: "Tool: file_checkpoints"
description: "The copies Marvi kept before changing files, and before risky commands."
-->
List what can be put back, newest first: copies of single files taken before file_write,
file_edit or file_delete, and whole-workspace snapshots taken before a terminal command
that could lose work. Each row says which kind it is and what prompted it. Read this
before file_restore, and when the user asks whether something can be undone. Only Marvi's
own tools and commands make these: a change made by another program or by the user by
hand has none, so an empty list means "no copy", not "nothing changed".
