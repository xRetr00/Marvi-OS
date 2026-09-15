<!--
name: "Tool: file_delete"
description: "Delete one file."
-->
Delete one file. Treat it as something that cannot be undone. Read it first: if what you
find does not match how the user described it, or you did not create it, say so instead
of deleting. Only on an explicit request. A copy of a file is kept first (file_restore
can bring it back), but a folder is not copied and old copies expire.
