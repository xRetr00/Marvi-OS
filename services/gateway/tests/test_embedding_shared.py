"""One embedding model per process, not one per memory connection.

`MemoryStore` is built per thread on purpose -- SQLite connections have thread
affinity and sharing one caused native crashes. The embedder was reached
through the store and silently inherited that, so every thread that touched
memory loaded its own copy of a 130MB model. Four in two minutes of one real
log, the first costing twelve seconds during a call join.
"""

from __future__ import annotations

import threading

from marvi_gateway import embedding


def _fresh(monkeypatch) -> None:
    monkeypatch.setattr(embedding, "_shared", None)
    # Nothing should be loaded to answer this question.
    monkeypatch.setattr(embedding, "warm", lambda _embedder: None)


def test_every_store_gets_the_same_embedder(monkeypatch) -> None:
    _fresh(monkeypatch)
    assert embedding.shared() is embedding.shared()


def test_it_is_warmed_once(monkeypatch) -> None:
    _fresh(monkeypatch)
    warmed: list[object] = []
    monkeypatch.setattr(embedding, "warm", warmed.append)

    threads = [threading.Thread(target=embedding.shared) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert len(warmed) == 1, f"loaded the model {len(warmed)} times"
