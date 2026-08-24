"""Knowledge graph, reflection, reinforcement, and the consolidation pass."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from marvi_gateway.memory import EPISODIC_TTL_DAYS, PROMOTE_AFTER_REPEATS, MemoryStore


@pytest.fixture
def memory(tmp_path):
    store = MemoryStore(tmp_path / "memory.sqlite3")
    yield store
    store.close()


# -- knowledge graph --------------------------------------------------------


def test_relations_are_traversable_in_both_directions(memory) -> None:
    memory.link("Shereef", "owns", "Tuya bulb")
    memory.link("Tuya bulb", "lives in", "bedroom")

    from_owner = {r["object"] for r in memory.neighbours("Shereef")}
    from_bulb = {(r["subject"], r["object"]) for r in memory.neighbours("Tuya bulb")}

    assert from_owner == {"Tuya bulb"}
    # The bulb is reachable as both a subject and an object.
    assert ("Shereef", "Tuya bulb") in from_bulb
    assert ("Tuya bulb", "bedroom") in from_bulb


def test_restating_a_fact_does_not_grow_the_graph(memory) -> None:
    first = memory.link("Shereef", "owns", "Tuya bulb")
    second = memory.link("Shereef", "owns", "Tuya bulb")

    assert first == second
    assert memory.graph_size() == {"entities": 2, "relations": 1}


def test_entity_lookup_is_case_insensitive(memory) -> None:
    memory.link("Shereef", "owns", "Tuya bulb")
    assert memory.neighbours("shereef")
    assert memory.neighbours("SHEREEF")


def test_deleting_an_entity_takes_its_relations_with_it(memory) -> None:
    memory.link("Shereef", "owns", "Tuya bulb")
    memory.link("Shereef", "owns", "ESP32")

    assert memory.forget_entity("Shereef") == 1
    assert memory.neighbours("Tuya bulb") == []
    assert memory.graph_size()["relations"] == 0


def test_graph_facts_carry_provenance_and_trust(memory) -> None:
    memory.link("Alex", "claims", "the invoice is paid", source="composio:gmail", trusted=False)
    relation = memory.neighbours("Alex")[0]

    assert relation["trusted"] is False
    assert relation["source"] == "composio:gmail"


def test_a_relation_needs_a_predicate_and_a_name(memory) -> None:
    with pytest.raises(ValueError, match="predicate"):
        memory.link("a", "  ", "b")
    with pytest.raises(ValueError, match="name"):
        memory.link("   ", "owns", "b")


# -- reinforcement ----------------------------------------------------------


def test_recall_strengthens_a_memory(memory) -> None:
    memory.remember("Bought a lamp", "from the corner shop")
    before = memory.export()[0]
    memory.search("lamp")
    after = memory.export()[0]

    assert before["body"] == after["body"]
    assert memory._db.execute("SELECT strength FROM memories").fetchone()["strength"] > 1


# -- reflection -------------------------------------------------------------


def test_repeated_episodes_are_promoted_to_a_durable_fact(memory) -> None:
    for _ in range(PROMOTE_AFTER_REPEATS):
        memory.remember("Turned the light down at night", "", kind="episodic")
    memory.remember("One-off thing", "", kind="episodic")

    result = memory.reflect()

    assert result["promoted"] == ["Turned the light down at night"]
    facts = [f["subject"] for f in memory.recent(kind="semantic")]
    assert "Turned the light down at night" in facts
    assert "One-off thing" not in facts


def test_reflection_is_idempotent(memory) -> None:
    for _ in range(PROMOTE_AFTER_REPEATS):
        memory.remember("Repeated thing", "", kind="episodic")

    first = memory.reflect()
    second = memory.reflect()

    assert first["promoted"] == ["Repeated thing"]
    assert second["promoted"] == []


def test_reflection_with_nothing_to_do_is_cheap_and_normal(memory) -> None:
    memory.remember("Only once", "", kind="episodic")
    assert memory.reflect() == {"considered": 0, "promoted": []}


def test_an_llm_summariser_can_replace_the_default_pass(memory) -> None:
    for _ in range(PROMOTE_AFTER_REPEATS):
        memory.remember("Coffee at nine", "", kind="episodic")

    seen: list[dict] = []

    def summarise(groups):
        seen.extend(groups)
        return [("Morning routine", "Shereef drinks coffee at nine")]

    result = memory.reflect(summarise=summarise)

    assert seen[0]["subject"] == "Coffee at nine"
    assert result["promoted"] == ["Morning routine"]
    assert memory.search("morning routine")[0]["body"] == "Shereef drinks coffee at nine"


def test_an_unavailable_llm_summariser_keeps_deterministic_reflection(memory) -> None:
    for _ in range(PROMOTE_AFTER_REPEATS):
        memory.remember("Fallback fact", "", kind="episodic")

    result = memory.reflect(summarise=lambda _groups: [])

    assert result["promoted"] == ["Fallback fact"]


# -- consolidation ----------------------------------------------------------


def _age(memory, memory_id: int, days: int) -> None:
    old = (datetime.now(UTC) - timedelta(days=days)).isoformat()
    memory._db.execute("UPDATE memories SET at = ? WHERE id = ?", (old, memory_id))
    memory._db.commit()


def test_consolidation_drops_stale_unused_episodes(memory) -> None:
    stale = memory.remember("Forgettable noise", "", kind="episodic")
    _age(memory, stale, EPISODIC_TTL_DAYS + 1)

    assert memory.consolidate()["forgotten"] == 1
    assert memory.count() == 0


def test_consolidation_never_drops_a_memory_that_was_used(memory) -> None:
    used = memory.remember("Something worth keeping", "", kind="episodic")
    _age(memory, used, EPISODIC_TTL_DAYS + 10)
    memory.search("worth keeping")  # recall reinforces it

    assert memory.consolidate()["forgotten"] == 0
    assert memory.count() == 1


def test_consolidation_never_drops_semantic_facts(memory) -> None:
    fact = memory.remember("Lives in Cairo", "", kind="semantic")
    _age(memory, fact, EPISODIC_TTL_DAYS * 5)

    assert memory.consolidate()["forgotten"] == 0
    assert memory.count() == 1


def test_consolidation_leaves_recent_episodes_alone(memory) -> None:
    memory.remember("Happened today", "", kind="episodic")
    assert memory.consolidate()["forgotten"] == 0
    assert memory.count() == 1


def test_consolidation_clears_entities_left_with_no_relations(memory) -> None:
    memory.link("Shereef", "owns", "Tuya bulb")
    memory.forget_entity("Shereef")

    # The bulb is now unreferenced; the sleep pass tidies it away.
    assert memory.consolidate()["orphan_entities"] == 1
    assert memory.graph_size() == {"entities": 0, "relations": 0}


def test_consolidation_keeps_entities_that_still_have_relations(memory) -> None:
    memory.link("Shereef", "owns", "Tuya bulb")
    assert memory.consolidate()["orphan_entities"] == 0
    assert memory.graph_size()["entities"] == 2


def test_world_summary_includes_the_graph(memory) -> None:
    memory.link("Shereef", "owns", "Tuya bulb")
    assert memory.world_summary()["graph"] == {"entities": 2, "relations": 1}


# -- ARC renderer projection ------------------------------------------------


def test_tree_projection_groups_memories_by_provenance(memory) -> None:
    memory.remember("Prefers terse replies", "Keep answers short", kind="semantic")
    memory.remember_external("Email from Sam", "Lunch tomorrow", source="composio:gmail")

    graph = memory.graph_export("tree")

    assert graph["mode"] == "tree"
    assert graph["nodes"][0] == {
        "id": "arc:memory", "kind": "root", "label": "Memory", "level": 2
    }
    sources = {n["label"] for n in graph["nodes"] if n["kind"] == "source"}
    assert sources == {"marvi", "composio:gmail"}
    untrusted = next(n for n in graph["nodes"] if n["label"] == "Email from Sam")
    assert untrusted["trusted"] is False
    assert untrusted["provenance"] == "composio:gmail"


def test_empty_tree_projection_is_an_empty_canvas(memory) -> None:
    assert memory.graph_export("tree") == {"mode": "tree", "nodes": [], "edges": []}


def test_contacts_projection_uses_explicit_relations(memory) -> None:
    memory.link("Sam", "works at", "Tiny Humans", source="user", trusted=True)

    graph = memory.graph_export("contacts")

    assert {n["label"] for n in graph["nodes"]} == {"Sam", "Tiny Humans"}
    assert graph["edges"][0]["label"] == "works at"
    assert graph["edges"][0]["provenance"] == "user"


def test_graph_projection_rejects_unknown_modes(memory) -> None:
    with pytest.raises(ValueError, match="unsupported graph mode"):
        memory.graph_export("galaxy")  # type: ignore[arg-type]
