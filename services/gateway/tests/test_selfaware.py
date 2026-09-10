"""Knowing where she lives, and knowing what she can do.

Both existed on disk and neither reached the model. The skills pipeline could
browse, review, install and remove skills, and `installed()` was read by the
CLI and one API route -- so a user could install a skill and the model would
never be told it was there. And Marvi could not read her own logs at all,
which is why a broken plugin turned into a voice session spent guessing.
"""

from __future__ import annotations

import pytest

from marvi_gateway import selfaware
from marvi_gateway.setup import skills

# -- the catalogue ------------------------------------------------------------


def test_the_skills_that_ship_with_marvi_are_found_without_installing_them() -> None:
    """They live in the checkout and are read from there.

    Copying them into the user's data directory at setup would have meant a
    second copy to keep level with the first, and a skill that silently stayed
    on an old version after an update.
    """
    found = {s.name for s in skills.installed()}

    assert "diagnose-myself" in found
    assert "marvi-agent" in found


def test_every_bundled_skill_is_valid_against_the_spec() -> None:
    """Marvi's own skills go through the same parser as one off the internet."""
    for skill in skills._read_dir(skills.BUNDLED, "marvi"):
        assert skill.name and skill.description
        assert len(skill.description) <= skills.MAX_DESCRIPTION
        assert skills.NAME_PATTERN.match(skill.name), skill.name
        assert skill.body.strip(), f"{skill.name} has no instructions"
        assert not skill.problems, f"{skill.name}: {skill.problems}"


def test_the_catalogue_advertises_without_disclosing() -> None:
    """Stage one is names and descriptions. The body is the expensive part and
    it must not be in the prompt, or progressive disclosure is just disclosure.
    """
    block = skills.advertise()

    assert "diagnose-myself" in block
    assert "skill_read" in block
    # A line out of the body of one of them. If this ever appears in the
    # catalogue, every skill is being loaded on every turn.
    assert "Start here" not in block


def test_an_empty_directory_advertises_nothing() -> None:
    """An empty heading is worse than no heading: it spends tokens saying
    there is nothing to say."""
    assert skills.advertise([]) == ""


def test_a_skill_body_is_read_by_name() -> None:
    skill = skills.body_of("using-tools")

    assert skill.name == "using-tools"
    assert "Read the result before describing it" in skill.body


def test_reading_a_skill_that_is_not_there_says_what_is() -> None:
    with pytest.raises(skills.SkillError):
        skills.body_of("no-such-skill")


def test_a_users_skill_overrides_one_of_marvis(tmp_path) -> None:
    """Theirs is the later and more deliberate choice."""
    directory = tmp_path / "marvi-agent"
    directory.mkdir()
    (directory / "SKILL.md").write_text(
        "---\nname: marvi-agent\ndescription: Mine, not yours.\n---\n\nBody.\n",
        encoding="utf-8",
    )

    found = {s.name: s for s in skills.installed(tmp_path)}

    assert found["marvi-agent"].description == "Mine, not yours."
    # And the rest of the bundled set is still there.
    assert "diagnose-myself" in found


# -- reading her own logs -----------------------------------------------------


def test_a_log_name_cannot_be_talked_into_a_path(monkeypatch, tmp_path) -> None:
    """The argument is a name inside the log directory, not a path.

    This is the whole reason `marvi_logs` exists rather than pointing the
    workspace root at the installation: the workspace root that would let her
    read a log also lets her delete a model.
    """
    monkeypatch.setenv("MARVI_LOG_DIR", str(tmp_path))
    (tmp_path / "gateway.log").write_text("fine\n", encoding="utf-8")

    for attempt in ("../../secrets", r"..\..\secrets", "/etc/passwd", ".ssh"):
        answer = selfaware.read_log(attempt)
        assert answer["ok"] is False, attempt


def test_a_log_is_read_from_the_end(monkeypatch, tmp_path) -> None:
    monkeypatch.setenv("MARVI_LOG_DIR", str(tmp_path))
    (tmp_path / "agent.log").write_text(
        "".join(f"line {i}\n" for i in range(100)), encoding="utf-8"
    )

    answer = selfaware.read_log("agent", lines=5)

    assert answer["ok"] is True
    assert answer["lines"] == [f"line {i}" for i in range(95, 100)]


def test_a_log_can_be_searched(monkeypatch, tmp_path) -> None:
    """Forty lines of the wrong thing is not an answer."""
    monkeypatch.setenv("MARVI_LOG_DIR", str(tmp_path))
    (tmp_path / "plugins.log").write_text(
        "loaded smart_room\nfailed to load smart_room\nloaded again\n", encoding="utf-8"
    )

    answer = selfaware.read_log("plugins", contains="FAILED")

    assert answer["matched"] == 1
    assert "failed to load" in answer["lines"][0]


def test_naming_a_log_that_is_not_there_lists_the_ones_that_are(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setenv("MARVI_LOG_DIR", str(tmp_path))
    (tmp_path / "gateway.log").write_text("x\n", encoding="utf-8")

    answer = selfaware.read_log("nonsense")

    assert answer["ok"] is False
    assert answer["available"] == ["gateway.log"]


def test_a_huge_line_cannot_crowd_out_the_rest(monkeypatch, tmp_path) -> None:
    """LiveKit logs whole SDP offers on one line. Without a cap, one of those
    is the entire reply."""
    monkeypatch.setenv("MARVI_LOG_DIR", str(tmp_path))
    (tmp_path / "livekit.log").write_text("x" * 50_000 + "\n", encoding="utf-8")

    answer = selfaware.read_log("livekit")

    assert len(answer["lines"][0]) == selfaware.MAX_LINE_CHARS


# -- where she lives ----------------------------------------------------------


def test_the_prompt_says_where_she_is_installed() -> None:
    """Not the source repository she was built from -- the installation she is
    actually running out of, which is where her logs and plugins are."""
    from marvi_gateway import paths

    block = selfaware.situation()

    assert str(paths.root()) in block
    assert str(paths.logs_dir()) in block
    assert "marvi_logs" in block


# -- and the same on both surfaces -------------------------------------------


def test_the_gateway_publishes_the_context_the_voice_worker_cannot_build() -> None:
    """Voice writes its own instructions in the Agent process.

    So everything the Gateway assembles for the typed surface reached chat and
    not speech -- the same shape of fault as voice having seven tools while
    chat had seventeen, which is why `/tools` exists. `/context` is that fix
    one level up, and this pins the two together: the Agent fetches this route
    and appends what it returns.
    """
    from fastapi.testclient import TestClient

    from marvi_gateway.app import create_app

    with TestClient(create_app()) as client:
        blocks = client.get("/context").json()["blocks"]

    joined = "\n".join(blocks)
    assert "diagnose-myself" in joined, "voice would not know any skill exists"
    assert "marvi_logs" in joined, "voice would not know where it is installed"


def test_the_agent_asks_for_that_route() -> None:
    """Nothing else keeps the two ends of this in step; they are different
    services in different Python environments."""
    from pathlib import Path

    agent = (
        Path(__file__).resolve().parents[3]
        / "services"
        / "agent"
        / "src"
        / "marvi_agent"
        / "tools.py"
    ).read_text(encoding="utf-8")

    assert '/context' in agent


# -- extending herself --------------------------------------------------------


def test_finding_a_skill_ranks_the_name_above_a_passing_mention(monkeypatch) -> None:
    """"brainstorm debugging" matched a library that mentioned debugging once,
    ahead of the skill actually called `brainstorming`. Eight results ranked by
    nothing is a list the model has to guess its way through."""
    monkeypatch.setattr(
        selfaware,
        "_catalogue",
        (
            9e9,  # far in the future, so the cache is never refreshed
            [
                {"name": "astropy", "description": "astronomy, useful when debugging orbits",
                 "repo": "a/b", "path": "astropy", "installed": False},
                {"name": "brainstorming", "description": "turn an idea into a design",
                 "repo": "obra/superpowers", "path": "skills/brainstorming", "installed": False},
            ],
        ),
    )

    found = selfaware.find_skills("brainstorming")

    assert found["skills"][0]["name"] == "brainstorming"


def test_installing_refuses_a_name_that_is_in_no_configured_source(monkeypatch) -> None:
    """The list is the list. A skill is instructions that change how Marvi
    behaves, so where it may come from is not something a model chooses."""
    monkeypatch.setattr(selfaware, "_catalogue", (9e9, []))

    answer = selfaware.install_skill("something-off-the-internet")

    assert answer["ok"] is False
    assert "configured sources" in answer["detail"]


def test_installing_a_skill_asks_first() -> None:
    """Finding is free; installing changes her own conduct, from a file
    written by somebody else."""

    class Registry:
        def __init__(self):
            self.specs = {}

        def register(self, spec):
            self.specs[spec.name] = spec

    registry = Registry()
    selfaware.register_store_tools(registry)

    assert registry.specs["skill_find"].sensitive is False
    assert registry.specs["skill_install"].sensitive is True


# -- what the model actually sends --------------------------------------------


def test_a_number_written_as_a_string_is_still_that_number() -> None:
    """The failure that made log reading useless.

    `marvi_logs(name="agent", lines="40")` was refused three times in a row
    with "argument lines must be int". Marvi spent her whole tool-call budget
    retrying, gave up, and answered from a log she had never read - inventing a
    cause out of the one partial line she did see.

    Models emit JSON and many write integers as strings, sometimes
    inconsistently within one session. A schema disagreement that only ever
    produces a refusal is a broken tool, not a strict one.
    """
    from marvi_gateway.tools import ToolRegistry, ToolSpec

    registry = ToolRegistry()
    spec = ToolSpec(
        name="marvi_logs",
        description="Read Marvi's own logs",
        arguments={},
        optional={"name": str, "lines": int, "contains": str},
        sensitive=False,
        handler=lambda **kwargs: kwargs,
    )
    registry.register(spec)

    accepted = registry.validate(spec, {"name": "agent", "lines": "40"})

    assert accepted["lines"] == 40
    assert isinstance(accepted["lines"], int)


def test_a_float_written_for_an_integer_is_read_as_the_integer() -> None:
    from marvi_gateway.tools import ToolRegistry, ToolSpec

    registry = ToolRegistry()
    spec = ToolSpec(
        name="dim",
        description="dim",
        arguments={"brightness": int},
        sensitive=False,
        handler=lambda **kwargs: kwargs,
    )

    assert registry.validate(spec, {"brightness": "60.0"})["brightness"] == 60


def test_nonsense_is_still_refused() -> None:
    """Coercion is for a number written as a string, not for hiding a real
    disagreement about what the argument means."""
    import pytest

    from marvi_gateway.tools import InvalidArgumentsError, ToolRegistry, ToolSpec

    registry = ToolRegistry()
    spec = ToolSpec(
        name="dim",
        description="dim",
        arguments={"brightness": int},
        sensitive=False,
        handler=lambda **kwargs: kwargs,
    )

    with pytest.raises(InvalidArgumentsError):
        registry.validate(spec, {"brightness": "quite bright"})


def test_a_string_argument_is_left_exactly_as_it_came() -> None:
    """"40" is a number; a search term that happens to be digits is not."""
    from marvi_gateway.tools import ToolRegistry, ToolSpec

    registry = ToolRegistry()
    spec = ToolSpec(
        name="marvi_logs",
        description="logs",
        arguments={},
        optional={"contains": str},
        sensitive=False,
        handler=lambda **kwargs: kwargs,
    )

    accepted = registry.validate(spec, {"contains": "1006"})

    assert accepted["contains"] == "1006"
    assert isinstance(accepted["contains"], str)


def test_a_boolean_written_as_a_word_is_read_as_one() -> None:
    from marvi_gateway.tools import ToolRegistry, ToolSpec

    registry = ToolRegistry()
    spec = ToolSpec(
        name="light",
        description="light",
        arguments={"on": bool},
        sensitive=False,
        handler=lambda **kwargs: kwargs,
    )

    assert registry.validate(spec, {"on": "false"})["on"] is False
    assert registry.validate(spec, {"on": "true"})["on"] is True


def test_a_stringified_object_is_still_that_object() -> None:
    """The same failure as the integer one, on the two biggest tools she has.

    `computer_action` was called with `arguments` as a JSON *string*. It was
    refused, and the model -- which cannot see that its own tool-calling layer
    stringified the nested field -- sent the identical call seven times:

        00:03:04  computer_action refused those arguments: argument
                  arguments must be dict
        ... six more, one every 1.4 seconds ...
        00:03:25  "The computer tools are rejecting my calls -- the arguments
                  schema is not accepting what I am sending."

    `arguments` is the nested field on both `computer_action` and
    `browser_action`, so this took the desktop and the browser out together.
    """
    from marvi_gateway.tools import ToolRegistry, ToolSpec

    registry = ToolRegistry()
    spec = ToolSpec(
        name="computer_action",
        description="Operate Windows applications",
        arguments={"action": str, "arguments": dict},
        sensitive=False,
        handler=lambda **kwargs: kwargs,
    )
    registry.register(spec)

    accepted = registry.validate(
        spec, {"action": "launch_app", "arguments": '{"app": "Spotify"}'}
    )
    assert accepted["arguments"] == {"app": "Spotify"}
    assert isinstance(accepted["arguments"], dict)

    # An object that was already an object is untouched.
    passed = registry.validate(spec, {"action": "launch_app", "arguments": {"app": "X"}})
    assert passed["arguments"] == {"app": "X"}


def test_a_string_that_is_not_the_declared_shape_is_still_refused() -> None:
    """Coercion reads a stringified object, not any string at all.

    A list where a dict was asked for is a different mistake, and accepting it
    would hide a real disagreement about what the argument means.
    """
    import pytest

    from marvi_gateway.tools import InvalidArgumentsError, ToolRegistry, ToolSpec

    registry = ToolRegistry()
    spec = ToolSpec(
        name="computer_action",
        description="Operate Windows applications",
        arguments={"action": str, "arguments": dict},
        sensitive=False,
        handler=lambda **kwargs: kwargs,
    )

    for wrong in ("[1, 2]", "not json at all", '"just a string"', "42"):
        with pytest.raises(InvalidArgumentsError, match="must be dict"):
            registry.validate(spec, {"action": "click", "arguments": wrong})


def _real_registry():
    """The computer and browser tools, registered the way the app registers them.

    Built from their own `register_*` functions rather than a hand-made
    fixture, because the bug was in what those functions produce.
    """
    from marvi_gateway.browser_api import register_workspace_browser_tools
    from marvi_gateway.computer import ComputerUse, register_computer_tools
    from marvi_gateway.tools import ToolRegistry

    registry = ToolRegistry()
    register_computer_tools(registry, ComputerUse())
    register_workspace_browser_tools(registry, lambda: None)
    return registry


#: What `schemas_from_registry` must publish for each Python type.
PUBLISHED_AS = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    dict: "object",
    list: "array",
}


def test_no_tool_advertises_a_type_its_own_validator_refuses() -> None:
    """The schema and the validator have to agree, or the tool cannot be called.

    `dict` and `list` were missing from the type map and fell through to
    `"string"`. So `computer_action` declared `arguments: dict`, published it
    as a string, and then refused the string the model dutifully sent:

        23 calls to computer_action, 23 HTTP 422s, not one success in the log.

    Six tools had it -- `clarify` and `room_set_light` among them.
    """
    from marvi_gateway.chat import schemas_from_registry

    registry = _real_registry()
    published = {row["name"]: row["parameters"] for row in schemas_from_registry(registry)}

    wrong: list[str] = []
    for spec in registry:
        if getattr(spec, "schema", None):
            continue  # Declares its own schema; not built from the signature.
        properties = published[spec.name].get("properties", {})
        for key, kind in {**spec.arguments, **spec.optional}.items():
            want = PUBLISHED_AS.get(kind)
            got = properties.get(key, {}).get("type")
            if want and got != want:
                wrong.append(f"{spec.name}.{key}: says {got!r}, validator wants {want!r}")
    assert not wrong, "schema contradicts the validator: " + "; ".join(sorted(wrong))


def test_every_python_type_has_a_json_type() -> None:
    """A type missing from the map silently becomes `"string"`, which is the bug."""
    from marvi_gateway.chat import schemas_from_registry
    from marvi_gateway.tools import ToolRegistry, ToolSpec

    registry = ToolRegistry()
    registry.register(
        ToolSpec(
            name="every_type",
            description="every type",
            arguments={f"a_{kind.__name__}": kind for kind in PUBLISHED_AS},
            sensitive=False,
            handler=lambda **kwargs: kwargs,
        )
    )
    properties = schemas_from_registry(registry)[0]["parameters"]["properties"]
    for kind, published in PUBLISHED_AS.items():
        assert properties[f"a_{kind.__name__}"]["type"] == published, kind
    # An array with no `items` is refused outright by some providers.
    assert properties["a_list"]["items"] == {}


def test_the_two_biggest_tools_say_what_goes_in_their_arguments() -> None:
    """`{"type": "object"}` alone says a shape is wanted and nothing about which.

    Both take a nested `arguments` object whose real schema lives somewhere
    else -- `computer_tools` for one, the page observation for the other -- so
    the description has to say where to look.
    """
    from marvi_gateway.chat import schemas_from_registry

    published = {
        row["name"]: row["parameters"] for row in schemas_from_registry(_real_registry())
    }
    for name, points_at in (("computer_action", "computer_tools"), ("browser_action", "tab_id")):
        field = published[name]["properties"]["arguments"]
        assert field["type"] == "object", name
        assert points_at in field.get("description", ""), name
        assert "never a string" in field["description"], name
