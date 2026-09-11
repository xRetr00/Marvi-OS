<!--
name: "Tool: file_write (coding)"
description: "Create a file or replace one completely. Ported from Claude Code's Write tool."
-->
Writes a file, replacing it entirely if it exists.

- If the file already exists, you must `file_read` it first. This overwrites
  everything without asking, so an unread file is a file whose contents you are
  about to lose.
- Prefer `file_edit` for any change to part of an existing file; it sends only
  the change and cannot lose the rest.
- Never create documentation or README files unless the job asks for them.
- Do not create a file the job does not need. Clutter someone else has to find
  and delete is not help.
- Do not add emojis to files unless asked.
