"""GPU detection, MCP servers, and skills.

Three concerns, one shared theme: each is a place where the obvious
implementation quietly does the wrong thing. A CPU wheel on a GPU machine. An
MCP server running a command nobody read. A skill granting itself tools.
"""

from __future__ import annotations

import json

import pytest

from marvi_gateway.setup import hardware, mcp, skills
from marvi_gateway.tools import ToolRegistry, ToolSpec

# -- GPU ------------------------------------------------------------------------


def test_no_gpu_means_no_question(monkeypatch) -> None:
    monkeypatch.delenv(hardware.PREFERENCE_ENV, raising=False)
    answer = hardware.question(hardware.Hardware(gpus=[]))

    assert answer["ask"] is False
    assert answer["use_gpu"] is False


def test_a_usable_gpu_is_asked_about(monkeypatch) -> None:
    monkeypatch.delenv(hardware.PREFERENCE_ENV, raising=False)
    found = hardware.Hardware(
        gpus=[hardware.Gpu("nvidia", "RTX 3060", memory_mb=12288, usable=True)]
    )
    answer = hardware.question(found)

    assert answer["ask"] is True
    assert "RTX 3060" in answer["prompt"]
    # Slower is the consequence people actually care about, so it is named.
    assert "slower" in answer["prompt"]


def test_a_card_with_no_driver_is_not_offered_as_a_choice(monkeypatch) -> None:
    monkeypatch.delenv(hardware.PREFERENCE_ENV, raising=False)
    found = hardware.Hardware(
        gpus=[hardware.Gpu("nvidia", "RTX 3060", memory_mb=12288, usable=False)]
    )
    answer = hardware.question(found)

    # Offering "GPU or CPU?" when the GPU cannot be driven offers a choice that
    # does not exist. Say what is missing instead.
    assert answer["ask"] is False
    assert answer["use_gpu"] is False
    assert "driver" in answer["reason"]


def test_a_saved_answer_is_not_asked_again(monkeypatch) -> None:
    monkeypatch.setenv(hardware.PREFERENCE_ENV, "0")
    found = hardware.Hardware(gpus=[hardware.Gpu("nvidia", "RTX 3060", usable=True)])

    assert hardware.question(found)["ask"] is False
    assert hardware.question(found)["use_gpu"] is False


def test_the_torch_index_matches_the_choice() -> None:
    # This one function is the whole point of the module.
    assert "cu" in hardware.torch_index(True)
    assert hardware.torch_index(False).endswith("/cpu")


# -- MCP --------------------------------------------------------------------------


@pytest.fixture
def mcp_file(tmp_path):
    return tmp_path / "mcp.json"


def test_npx_gets_the_flag_that_stops_it_hanging() -> None:
    # Without -y, npx stops to ask and the handshake times out with nothing to
    # explain why.
    assert mcp.normalise("x", "npx", ["@scope/pkg"], {}).args[0] == "-y"


def test_python_servers_get_unbuffered_output() -> None:
    # Buffered stdout over stdio looks exactly like a hung server.
    assert mcp.normalise("x", "uvx", ["srv"], {}).env["PYTHONUNBUFFERED"] == "1"


def test_preparing_shows_the_exact_command_and_writes_nothing(mcp_file) -> None:
    prepared = mcp.prepare("files", "npx", ["@scope/fs", "/tmp"])

    assert prepared["command"] == "npx -y @scope/fs /tmp"
    assert "runs a program on your machine" in prepared["notice"]
    assert not mcp_file.exists()


def test_an_unrecognised_runner_is_flagged() -> None:
    prepared = mcp.prepare("odd", "some-random-binary", [])

    assert any("not a runner Marvi recognises" in w for w in prepared["warnings"])


def test_adding_requires_the_token_from_preparing(mcp_file) -> None:
    assert mcp.add("made-up-token", mcp_file)["ok"] is False
    assert mcp.read(mcp_file) == {}


def test_a_token_is_single_use(mcp_file) -> None:
    token = mcp.prepare("files", "npx", ["@scope/fs"])["token"]

    assert mcp.add(token, mcp_file)["ok"] is True
    # Replaying an approval must not add it a second time.
    assert mcp.add(token, mcp_file)["ok"] is False


def test_the_saved_format_is_the_one_everybody_uses(mcp_file) -> None:
    token = mcp.prepare("files", "npx", ["@scope/fs"])["token"]
    mcp.add(token, mcp_file)
    saved = json.loads(mcp_file.read_text(encoding="utf-8"))

    # Claude Desktop, Claude Code, Cursor and VS Code all read this shape, so a
    # server configured elsewhere pastes straight in.
    assert saved["mcpServers"]["files"]["command"] == "npx"
    assert saved["mcpServers"]["files"]["args"][0] == "-y"


def test_a_server_can_be_disabled_without_losing_its_config(mcp_file) -> None:
    token = mcp.prepare("files", "npx", ["@scope/fs"])["token"]
    mcp.add(token, mcp_file)
    mcp.set_enabled("files", False, mcp_file)
    servers = mcp.read(mcp_file)

    assert servers["files"].enabled is False
    assert servers["files"].args  # still remembers how it was set up


def test_removing_an_unknown_server_says_so(mcp_file) -> None:
    assert mcp.remove("nope", mcp_file)["ok"] is False


# -- skills -------------------------------------------------------------------------

VALID = (
    "---\n"
    "name: pdf-processing\n"
    "description: Extract text from PDFs. Use when handling PDF documents.\n"
    "---\n\nDo the thing.\n"
)


def registry() -> ToolRegistry:
    tools = ToolRegistry()
    tools.register(
        ToolSpec(name="read_file", description="r", arguments={}, sensitive=False,
                 handler=lambda: 1)
    )
    tools.register(
        ToolSpec(name="send_email", description="e", arguments={}, sensitive=True,
                 handler=lambda: 1)
    )
    return tools


def test_a_valid_skill_parses() -> None:
    skill = skills.parse(VALID)

    assert skill.name == "pdf-processing"
    assert skill.body.strip() == "Do the thing."


@pytest.mark.parametrize(
    "name", ["PDF-Processing", "-pdf", "pdf-", "pdf--processing", "x" * 65, "has space"]
)
def test_names_that_break_the_spec_are_refused(name) -> None:
    with pytest.raises(skills.SkillError):
        skills.parse(f"---\nname: {name}\ndescription: Something.\n---\n\nBody.\n")


def test_missing_required_fields_are_refused() -> None:
    with pytest.raises(skills.SkillError, match="description"):
        skills.parse("---\nname: thing\n---\n\nBody.\n")
    with pytest.raises(skills.SkillError, match="name"):
        skills.parse("---\ndescription: A thing.\n---\n\nBody.\n")


def test_no_frontmatter_is_refused() -> None:
    with pytest.raises(skills.SkillError, match="frontmatter"):
        skills.parse("Just some markdown.\n")


def test_optional_fields_are_read() -> None:
    skill = skills.parse(
        "---\nname: thing\ndescription: A thing.\nlicense: MIT\n"
        "compatibility: Requires git\nmetadata:\n  author: someone\n---\n\nBody.\n"
    )

    assert skill.license == "MIT"
    assert skill.compatibility == "Requires git"
    assert skill.metadata == {"author": "someone"}


def test_a_skill_cannot_grant_itself_a_tool_that_does_not_exist() -> None:
    skill = skills.parse(
        "---\nname: greedy\ndescription: Wants things.\n"
        "allowed-tools: read_file delete_everything\n---\n\nBody.\n"
    )
    resolved = skills.permitted_tools(skill, registry())

    assert "delete_everything" not in resolved["tools"]
    assert resolved["unknown"] == ["delete_everything"]


def test_naming_a_sensitive_tool_does_not_pre_approve_it() -> None:
    skill = skills.parse(
        "---\nname: greedy\ndescription: Wants things.\n"
        "allowed-tools: send_email\n---\n\nBody.\n"
    )

    # The whole point. Otherwise any skill grants itself anything by editing a
    # text file the user probably did not read.
    assert skills.permitted_tools(skill, registry())["still_sensitive"] == ["send_email"]


def test_declaring_tools_narrows_rather_than_widens() -> None:
    narrow = skills.parse(
        "---\nname: narrow\ndescription: Modest.\nallowed-tools: read_file\n---\n\nB.\n"
    )
    silent = skills.parse("---\nname: silent\ndescription: Says nothing.\n---\n\nB.\n")

    assert skills.permitted_tools(narrow, registry())["tools"] == ["read_file"]
    # No declaration means the normal set, not everything unlocked.
    assert set(skills.permitted_tools(silent, registry())["tools"]) == {
        "read_file",
        "send_email",
    }


def test_review_shows_the_instructions_before_installing() -> None:
    reviewed = skills.review(skills.parse(VALID), registry())

    # Instructions that will shape behaviour, so shown rather than summarised.
    assert reviewed["instructions"].strip() == "Do the thing."


def test_review_warns_about_a_tool_declaration() -> None:
    skill = skills.parse(
        "---\nname: greedy\ndescription: Wants things.\n"
        "allowed-tools: send_email\n---\n\nBody.\n"
    )
    warnings = " ".join(skills.review(skill, registry())["warnings"])

    assert "request, never a grant" in warnings


def test_a_skill_whose_name_disagrees_with_its_folder_is_refused(tmp_path) -> None:
    directory = tmp_path / "wrong-folder"
    directory.mkdir()
    (directory / "SKILL.md").write_text(VALID, encoding="utf-8")

    # The spec requires they match, and a mismatch is how one skill quietly
    # overwrites another on install.
    with pytest.raises(skills.SkillError, match="folder"):
        skills.read_skill(directory)


def test_installing_copies_the_known_layout(tmp_path) -> None:
    source = tmp_path / "pdf-processing"
    (source / "scripts").mkdir(parents=True)
    (source / "SKILL.md").write_text(VALID, encoding="utf-8")
    (source / "scripts" / "run.py").write_text("pass\n", encoding="utf-8")

    base = tmp_path / "skills"
    assert skills.install_from(source, base)["ok"] is True
    assert (base / "pdf-processing" / "SKILL.md").exists()
    # Scripts are copied, never executed at install time.
    assert (base / "pdf-processing" / "scripts" / "run.py").exists()


def test_installed_skills_are_listed(tmp_path) -> None:
    source = tmp_path / "pdf-processing"
    source.mkdir()
    (source / "SKILL.md").write_text(VALID, encoding="utf-8")
    base = tmp_path / "skills"
    skills.install_from(source, base)

    assert [s.name for s in skills.installed(base)] == ["pdf-processing"]


def test_removing_cannot_escape_the_skills_folder(tmp_path) -> None:
    base = tmp_path / "skills"
    base.mkdir()
    outside = tmp_path / "important"
    outside.mkdir()

    assert skills.remove("../important", base)["ok"] is False
    assert outside.exists()


# -- paths --------------------------------------------------------------------------


def test_every_path_derives_from_one_root(monkeypatch, tmp_path) -> None:
    from marvi_gateway import paths

    monkeypatch.setenv("MARVI_HOME", str(tmp_path / "root"))
    for name in ("MARVI_LOG_DIR", "MARVI_JOURNAL_DB", "MARVI_CHAT_DB",
                 "MARVI_IDENTITY_DIR", "MARVI_TOKEN_STORE", "MARVI_PROVIDER_CONFIG",
                 "MARVI_MEMORY_DB", "MARVI_AUDIT_LOG",
                 "MARVI_MODEL_ROOT", "MARVI_RUNTIME_ROOT", "MARVI_SKILLS_DIR",
                 "MARVI_MCP_CONFIG"):
        monkeypatch.delenv(name, raising=False)

    described = paths.describe()
    # Nine modules each writing their own literal is how two folders happened.
    for value in described.values():
        assert value.startswith(str(tmp_path / "root"))


def test_a_space_free_root(monkeypatch, tmp_path) -> None:
    from marvi_gateway import paths

    monkeypatch.delenv("MARVI_HOME", raising=False)
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))

    # A space in a path is a nuisance in every shell.
    assert " " not in paths.root().name


def test_the_old_folder_is_migrated_not_abandoned(monkeypatch, tmp_path) -> None:
    from marvi_gateway import paths

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("MARVI_HOME", raising=False)
    old = tmp_path / paths.LEGACY_FOLDER
    old.mkdir()
    (old / "journal.sqlite3").write_bytes(b"real data")

    moved = paths.migrate_legacy()

    assert "journal.sqlite3" in moved
    assert (paths.root() / "journal.sqlite3").read_bytes() == b"real data"


def test_migration_never_overwrites(monkeypatch, tmp_path) -> None:
    from marvi_gateway import paths

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("MARVI_HOME", raising=False)
    old = tmp_path / paths.LEGACY_FOLDER
    old.mkdir()
    (old / "journal.sqlite3").write_bytes(b"old")
    new = paths.root()
    new.mkdir(parents=True)
    (new / "journal.sqlite3").write_bytes(b"new")

    paths.migrate_legacy()

    # Guessing which of two journals is the real one is not a decision to make
    # silently, so the newer root wins and the old file stays put.
    assert (new / "journal.sqlite3").read_bytes() == b"new"
    assert (old / "journal.sqlite3").exists()


def test_migration_runs_once(monkeypatch, tmp_path) -> None:
    from marvi_gateway import paths

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.delenv("MARVI_HOME", raising=False)
    old = tmp_path / paths.LEGACY_FOLDER
    old.mkdir()
    (old / "thing.txt").write_text("x", encoding="utf-8")

    assert paths.migrate_legacy() == ["thing.txt"]
    (old / "later.txt").write_text("y", encoding="utf-8")
    assert paths.migrate_legacy() == []
