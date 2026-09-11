<!--
name: "Tool: glob"
description: "Find files whose path matches a glob pattern, newest first."
-->
Find files whose path matches a glob pattern -- `**/*.py`, `src/**/test_*.ts` --
newest first, so the file that was just changed comes before the rest. A pattern with
no slash matches a file name at any depth. Dependency and build folders
(`node_modules`, `.venv`, `target`, `dist`) are never walked. Use it when you know what a
file is called but not where it is; to find what is *in* files, use grep. Faster and
tidier than listing folders one by one or reaching for `dir` in the terminal.
