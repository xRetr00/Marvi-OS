"""The tools Harvi codes with: ranged reads, glob, grep, and background commands.

Each is the smallest form of what a coding harness needs and Marvi's file tools
lacked: a read of lines 200-260 of a long file rather than the first 200 KB of
it, "which files match `**/*.py`" as its own question, a grep that can say only
which files match or show the lines around a hit, and a test suite that keeps
running while the agent does something else.
"""

from __future__ import annotations

import os
import sys
import time

import pytest

from marvi_gateway.filepolicy import ROOT_SETTING
from marvi_gateway.tools import ToolRegistry
from marvi_gateway.workspace import Workspace, WorkspaceRefusedError, register_workspace_tools


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    monkeypatch.setenv(ROOT_SETTING, str(tmp_path))
    monkeypatch.delenv("MARVI_FILE_READ_SCOPE", raising=False)
    monkeypatch.delenv("MARVI_PATH_BLACKLIST", raising=False)
    files = {
        "src/voice.py": "import os\n\nLEAD = 0.6\n\n\ndef speak():\n    return LEAD\n",
        "src/island.ts": "export const LEAD = 1;\n",
        "README.md": "# Marvi\nlead is tunable\n",
        "node_modules/dep.py": "LEAD = 9\n",
    }
    for name, text in files.items():
        (tmp_path / name).parent.mkdir(exist_ok=True)
        (tmp_path / name).write_bytes(text.encode("utf-8"))
    old = time.time() - 100
    os.utime(tmp_path / "src" / "island.ts", (old, old))
    return Workspace()


def test_a_ranged_read_is_numbered(workspace) -> None:
    found = workspace.read("src/voice.py", offset=3, limit=2)
    assert found["text"] == "     3\tLEAD = 0.6\n     4\t"
    assert found["lines"] == {"from": 3, "to": 4, "of": 7}


def test_a_plain_read_is_unchanged(workspace) -> None:
    assert workspace.read("src/voice.py")["text"].startswith("import os\n")


def test_glob_finds_by_pattern_newest_first_and_skips_dependencies(workspace) -> None:
    found = workspace.glob("**/*")
    paths = list(found["files"])
    assert "node_modules/dep.py" not in paths
    assert paths.index("src/voice.py") < paths.index("src/island.ts")
    assert workspace.glob("**/*.py")["files"] == ["src/voice.py"]


def test_grep_says_which_files_by_default(workspace) -> None:
    assert workspace.grep("LEAD")["files"] == ["src/island.ts", "src/voice.py"]


def test_grep_content_has_line_numbers_and_context(workspace) -> None:
    found = workspace.grep("return", output_mode="content", before=1)
    assert found["lines"] == ["src/voice.py-6-def speak():", "src/voice.py:7:    return LEAD"]


def test_grep_counts_filters_and_cases(workspace) -> None:
    assert workspace.grep("LEAD", output_mode="count")["counts"] == {
        "src/island.ts": 1,
        "src/voice.py": 2,
    }
    assert workspace.grep("LEAD", type="py")["files"] == ["src/voice.py"]
    assert workspace.grep("LEAD", glob="*.ts")["files"] == ["src/island.ts"]
    assert workspace.grep("lead")["files"] == ["README.md"]
    assert workspace.grep("lead", case_insensitive=True)["files"] == [
        "README.md", "src/island.ts", "src/voice.py",
    ]


def test_grep_can_match_across_lines(workspace) -> None:
    assert workspace.grep(r"speak\(\):\n\s+return", multiline=True)["files"] == ["src/voice.py"]
    assert workspace.grep(r"speak\(\):\n\s+return")["files"] == []


def test_grep_limits_what_it_returns(workspace) -> None:
    found = workspace.grep("LEAD", output_mode="content", head_limit=1)
    assert len(found["lines"]) == 1 and "more" in found


def test_grep_refuses_a_broken_pattern_helpfully(workspace) -> None:
    with pytest.raises(WorkspaceRefusedError, match="not a valid regular expression"):
        workspace.grep("speak(")


def test_a_background_command_is_read_later(workspace, tmp_path) -> None:
    script = tmp_path / "slow.py"
    script.write_text(
        "import time\nprint('first', flush=True)\ntime.sleep(0.3)\nprint('second')\n",
        encoding="utf-8",
    )
    started = workspace.run(f"{sys.executable} {script}", shell="cmd", background=True)
    assert started["background"] is True and started["pid"]

    deadline = time.monotonic() + 15
    seen = ""
    while True:
        output = workspace.output(started["pid"])
        seen += output["output"]
        if not output["running"]:
            break
        assert time.monotonic() < deadline
        time.sleep(0.1)
    assert "first" in seen and "second" in seen
    assert output["exit_code"] == 0
    # Read once: the next read has nothing new.
    assert workspace.output(started["pid"])["output"] == ""


def test_output_of_an_unknown_process_is_refused(workspace) -> None:
    with pytest.raises(WorkspaceRefusedError, match="no background command"):
        workspace.output(4242)


def test_the_tools_are_registered(workspace) -> None:
    registry = ToolRegistry()
    register_workspace_tools(registry, workspace)
    names = {spec.name for spec in registry}
    assert {"glob", "grep", "process_output"} <= names
    assert not registry.get("grep").sensitive and not registry.get("glob").sensitive
    assert "background" in registry.get("terminal_run").optional
    assert {"offset", "limit"} <= set(registry.get("file_read").optional)
    for name in ("glob", "grep", "process_output"):
        assert len(registry.get(name).description) >= 120, name
