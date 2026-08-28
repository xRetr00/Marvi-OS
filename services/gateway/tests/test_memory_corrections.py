"""A memory store that can be corrected.

`remember` was an unconditional INSERT, so a correction did not replace a fact
-- it joined it. From the real store, over two minutes of one conversation:

    #20  The user's name is Sheriff and they are the developer of Marvi.
    #21  The user's name is Sheriff (one F), and they are the developer.
    #22  The user's name is Shrif, and they are the developer of Marvi.
    #23  The user's name is Shreef (spelled S-H-R-E-E-F), ...
    #24  The user's name is Shreef, spelled S-H-E-R-E-E-F, ...

Five memories, one fact, five spellings. The recogniser hears a name
differently each time, the user corrects it, and every correction was stored as
an additional truth -- so recall returns all five and nothing marks which one
is current.
"""

from __future__ import annotations

import pytest

from marvi_gateway.memory import MemoryStore

NAME = "The user's name is {}, and they are the developer of Marvi."


@pytest.fixture
def store(tmp_path):
    made = MemoryStore(tmp_path / "memory.sqlite3")
    yield made
    made.close()


def test_a_correction_replaces_rather_than_accumulates(store) -> None:
    """The exact sequence from the real store, in order."""
    for spelling in ("Sheriff", "Sheriff (one F)", "Shrif", "Shreef"):
        store.remember(spelling, NAME.format(spelling), kind="semantic")

    kept = [row for row in store.recent(limit=20) if "name is" in row["body"]]

    assert len(kept) == 1, [row["body"] for row in kept]
    assert "Shreef" in kept[0]["body"]


def test_the_correction_keeps_the_same_id(store) -> None:
    """In place, so anything already pointing at the memory points at the
    corrected version rather than at a hole."""
    first = store.remember("Sheriff", NAME.format("Sheriff"), kind="semantic")
    second = store.remember("Shreef", NAME.format("Shreef"), kind="semantic")

    assert first == second


def test_search_finds_the_new_text_and_not_the_old(store) -> None:
    """An external-content FTS5 index does not follow an UPDATE on its own.
    Without the trigger this is the duplicate problem again, one layer down
    where nobody would look for it."""
    store.remember("Sheriff", NAME.format("Sheriff"), kind="semantic")
    store.remember("Shreef", NAME.format("Shreef"), kind="semantic")

    assert store.search("Shreef"), "the corrected spelling must be findable"
    assert not store.search("Sheriff"), "the superseded spelling must not be"


def test_two_different_facts_both_survive(store) -> None:
    """The failure this must not have. Merging unrelated facts loses one
    silently, which is worse than the duplication it exists to stop."""
    store.remember("name", "The user's name is Shreef.", kind="semantic")
    store.remember("coffee", "The user drinks coffee black, no sugar.", kind="semantic")
    store.remember("hours", "The user works late and sleeps past midday.", kind="semantic")

    assert len(store.recent(limit=20)) == 3


def test_a_short_fact_is_never_superseded(store) -> None:
    """"Likes tea" and "likes coffee" share almost every word and mean the
    opposite, so a statement too short to judge is left alone."""
    store.remember("drink", "Likes tea.", kind="semantic")
    store.remember("drink", "Likes coffee.", kind="semantic")

    assert len(store.recent(limit=20)) == 2


def test_episodic_memories_never_supersede(store) -> None:
    """Two records of a moment are not a contradiction; they are two moments."""
    for _ in range(3):
        store.remember("Hello", "The user said hello and Marvi replied.", kind="episodic")

    assert len(store.recent(limit=20)) == 3


def test_an_untrusted_memory_never_corrects_a_trusted_one(store) -> None:
    """A web page must not be able to rewrite what the user told Marvi. That
    would be a prompt injection laundering itself through the store."""
    store.remember("name", NAME.format("Shreef"), kind="semantic")
    store.remember_external("name", NAME.format("Mallory"), source="web", kind="semantic")

    bodies = [row["body"] for row in store.recent(limit=20)]
    assert len(bodies) == 2
    assert any("Shreef" in body for body in bodies)


def test_a_related_but_different_fact_is_not_swallowed(store) -> None:
    """Containment's failure mode, checked rather than assumed. These two share
    the frame and differ in the subject, which is what a correction looks like
    from the outside -- and they are two people."""
    store.remember("name", "The user's name is Shreef, developer of Marvi.", kind="semantic")
    store.remember("brother", "The user's brother is Ahmed, developer of Marvi.", kind="semantic")

    assert len(store.recent(limit=20)) == 2


def test_forgetting_a_memory_takes_its_vector_with_it(store) -> None:
    """`ON DELETE CASCADE` is decoration until foreign keys are switched on,
    and SQLite defaults them off. The join hides the leak -- an orphan vector
    matches no row -- which is exactly why nobody would have noticed it."""
    memory_id = store.remember("tea", "The user prefers tea to coffee.", kind="semantic")
    store._db.execute(
        "INSERT OR REPLACE INTO vectors VALUES (?, ?, ?, ?)", (memory_id, "m", 2, b"\x00" * 8)
    )
    store._db.commit()

    store.forget(memory_id)

    assert store._db.execute("SELECT COUNT(*) FROM vectors").fetchone()[0] == 0

# -- what 147 imported memories exposed in recall ------------------------------


def test_a_question_made_of_common_words_does_not_match_everything(tmp_path) -> None:
    """`who am I` became `"who" OR "am" OR "I"`, which matches every memory
    containing the word I -- and FTS5 ranked one about development style above
    the four entries naming the user, which semantic search had found.

    A question with no distinctive words is exactly the question keywords
    cannot help with, so the right keyword answer is none at all.
    """
    from marvi_gateway.memory import _fts_query

    assert _fts_query("who am I") == ""
    assert _fts_query("how should you talk to me") == '"talk"'
    # A real term still searches; only the words that match everything go.
    assert _fts_query("what computer do I have") == '"computer"'
    assert _fts_query("Shereef") == '"Shereef"'


def test_operator_syntax_is_still_quoted_away(tmp_path) -> None:
    """The reason this function exists. Dropping stopwords must not drop the
    quoting that stops user text becoming FTS5 operators."""
    from marvi_gateway.memory import _fts_query

    assert _fts_query('NEAR("a" "b") OR x*') == '"NEAR" OR "b" OR "x"'


def test_keyword_and_semantic_are_interleaved_not_concatenated(tmp_path) -> None:
    """Keyword results used to lead, all of them, which holds while the store
    is small and a literal hit is therefore rare. With 147 memories, "what
    computer do I have" matched "Computer Engineering" literally and buried the
    entry naming the actual machine.
    """
    store = MemoryStore(tmp_path / "m.db")
    literal = store.remember("computer science", "The user studies Computer Engineering.")
    meaning = store.remember("the machine", "The user's desktop has an RTX 3060 and a Ryzen 5.")

    # Semantic search stands in for the embedder, which is off in tests.
    store.search_similar = lambda query, limit=10: [  # type: ignore[method-assign]
        entry for entry in store.recent(limit=50) if entry["id"] == meaning
    ]

    found = [row["id"] for row in store.search("what computer do I have", limit=2)]

    assert found == [literal, meaning]


def test_an_import_marks_where_each_memory_came_from(tmp_path) -> None:
    """A prefix rather than a guess at the file extension. The first version
    matched `%.md` and friends, so a memory imported from Honcho -- whose
    source is `honcho/hermes`, not a filename -- fell through to the full
    external-data envelope, and 154 of those would have filled the recall
    budget many times over."""
    store = MemoryStore(tmp_path / "m.db")
    store.remember_external(
        "hardware", "The user has an RTX 3060.", source=f"{store.IMPORTED}honcho/hermes"
    )

    block = store.recall_block("RTX 3060")

    assert "(from honcho/hermes) The user has an RTX 3060." in block
    assert "EXTERNAL DATA" not in block
