"""Where embeddings come from, when memory starts using them.

Semantic recall is the last gap in memory: FTS5 cannot match "who am I"
against "the user's name is Shereef", because they share no words. Closing it
needs a vector for every memory and one per query, and that is a choice with
real trade-offs rather than a detail to hardcode:

* **local** keeps memory on this machine, which is the whole premise of Marvi,
  and spends CPU that Parakeet is already using;
* **a provider** costs a network round trip on every recall and sends the text
  of your memories to somebody else, and is the right answer on a thin laptop
  or when the local model will not install.

So it is a setting, and `off` is the default -- because keyword recall works
today and a memory system that silently started calling an API would be a
surprise nobody asked for.

## OpenAI-compatible, not OpenAI

The provider option speaks `POST /v1/embeddings`. That is what OpenAI, Ollama,
LM Studio, llama.cpp, LocalAI, vLLM, TEI, Jina, Voyage and Together all serve,
so "provider" covers both a cloud key and a model running on the machine next
to this one. One shape, and the base URL decides which.
"""

from __future__ import annotations

import os
from typing import Any

from .logs import get_logger

log = get_logger("memory")

SOURCE_SETTING = "MARVI_EMBEDDING_SOURCE"
MODEL_SETTING = "MARVI_EMBEDDING_MODEL"
URL_SETTING = "MARVI_EMBEDDING_URL"
KEY_SETTING = "MARVI_EMBEDDING_KEY"

OFF, LOCAL, PROVIDER = "off", "local", "provider"
SOURCES = (OFF, LOCAL, PROVIDER)

#: Small, permissively licensed, and fast enough on a CPU that is already busy.
#: Measured on this machine rather than chosen from a leaderboard.
DEFAULT_LOCAL_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
DEFAULT_PROVIDER_MODEL = "text-embedding-3-small"

#: A recall that has not answered by now is worse than a keyword search that
#: has. This sits in front of every turn.
TIMEOUT = 8.0


def source() -> str:
    value = os.environ.get(SOURCE_SETTING, "").strip().lower()
    return value if value in SOURCES else OFF


def model_name() -> str:
    configured = os.environ.get(MODEL_SETTING, "").strip()
    if configured:
        return configured
    return DEFAULT_LOCAL_MODEL if source() == LOCAL else DEFAULT_PROVIDER_MODEL


def base_url() -> str:
    return os.environ.get(URL_SETTING, "").strip().rstrip("/")


class Embedder:
    """Text to vectors, from wherever the setting says.

    Returns `[]` rather than raising when it cannot answer. Every caller has a
    keyword search to fall back on, and a memory system that fails a turn
    because an embedding endpoint was down would be a worse system than the one
    that had no embeddings at all.
    """

    def __init__(self) -> None:
        self._local: Any = None

    @property
    def ready(self) -> bool:
        return source() != OFF

    def embed(self, texts: list[str]) -> list[list[float]]:
        wanted = [text for text in texts if text.strip()]
        if not wanted or not self.ready:
            return []
        try:
            if source() == LOCAL:
                return self._locally(wanted)
            return self._from_provider(wanted)
        except Exception as exc:
            log.warning(
                "embeddings unavailable; falling back to keyword recall: %s", exc,
                extra={"marvi_source": source(), "marvi_model": model_name()},
            )
            return []

    def _locally(self, texts: list[str]) -> list[list[float]]:
        if self._local is None:
            from sentence_transformers import SentenceTransformer

            # CPU explicitly. The card is busy speaking, and an embedding model
            # that competes with Kokoro for it would trade a fast recall for a
            # stuttering voice.
            self._local = SentenceTransformer(model_name(), device="cpu")
            log.info("embeddings: %s loaded on the CPU", model_name())
        return [vector.tolist() for vector in self._local.encode(texts)]

    def _from_provider(self, texts: list[str]) -> list[list[float]]:
        import httpx

        url = base_url()
        if not url:
            raise RuntimeError(f"no endpoint configured; set {URL_SETTING}")
        headers = {"content-type": "application/json"}
        if key := os.environ.get(KEY_SETTING, "").strip():
            headers["authorization"] = f"Bearer {key}"
        response = httpx.post(
            f"{url}/embeddings",
            json={"model": model_name(), "input": texts},
            headers=headers,
            timeout=TIMEOUT,
        )
        response.raise_for_status()
        rows = response.json().get("data") or []
        # Sorted by index, because the spec permits any order and a silently
        # mismatched vector is a memory that recalls the wrong thing.
        rows.sort(key=lambda row: int(row.get("index", 0)))
        return [list(row.get("embedding") or []) for row in rows]


def describe() -> dict[str, Any]:
    """The setting, for the memory page."""
    return {
        "source": source(),
        "sources": list(SOURCES),
        "model": model_name(),
        "url": base_url(),
        "key_set": bool(os.environ.get(KEY_SETTING, "").strip()),
        "settings": {
            "source": SOURCE_SETTING,
            "model": MODEL_SETTING,
            "url": URL_SETTING,
            "key": KEY_SETTING,
        },
        "default_local_model": DEFAULT_LOCAL_MODEL,
        "default_provider_model": DEFAULT_PROVIDER_MODEL,
    }
