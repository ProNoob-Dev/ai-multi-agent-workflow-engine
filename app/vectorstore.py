"""Vector search for the PolicyAgent's RAG retrieval.

Default: a deterministic in-memory store. Documents are embedded with a
hashed bag-of-words vector (no model download, no API key) and ranked by
cosine similarity. When QDRANT_URL is set, the same hashed embeddings are
stored in a real Qdrant collection instead.
"""

import hashlib
import math
import re

from . import config

DIM = 256
_TOKEN_RE = re.compile(r"[a-z0-9]+")

# Common words carry no meaning for retrieval; dropping them stops
# generic sections from outranking the right one on "the"/"what" alone.
STOPWORDS = {
    "the",
    "is",
    "a",
    "an",
    "what",
    "how",
    "can",
    "i",
    "do",
    "does",
    "we",
    "you",
    "are",
    "was",
    "were",
    "be",
    "been",
    "to",
    "of",
    "in",
    "on",
    "for",
    "with",
    "and",
    "or",
    "by",
    "at",
    "from",
    "it",
    "its",
    "this",
    "that",
    "as",
    "if",
    "my",
    "our",
    "your",
    "me",
    "us",
    "am",
}


def _norm(token: str) -> str | None:
    """Lower-case normalisation: drop stopwords, strip simple plurals
    (expenses -> expense) so query and document tokens match."""
    if token in STOPWORDS:
        return None
    if len(token) > 4 and token.endswith("es"):
        return token[:-2]
    if len(token) > 3 and token.endswith("s"):
        return token[:-1]
    return token


def embed(text: str, dim: int = DIM) -> list[float]:
    """Deterministic hashed bag-of-words embedding, L2-normalised."""
    vec = [0.0] * dim
    for raw in _TOKEN_RE.findall(text.lower()):
        token = _norm(raw)
        if token is None:
            continue
        idx = int(hashlib.md5(token.encode()).hexdigest(), 16) % dim
        vec[idx] += 1.0
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b))


def hybrid_score(query: str, doc_text: str, cosine: float) -> float:
    """Blend vector cosine (70%) with exact token overlap (30%).

    Pure hashed cosine can rank a long generic section above the right
    one on a shared common word; the overlap term rewards documents
    that actually contain the query's distinctive words.
    """
    query_tokens = {
        t for t in (_norm(tok) for tok in _TOKEN_RE.findall(query.lower())) if t
    }
    doc_tokens = {
        t for t in (_norm(tok) for tok in _TOKEN_RE.findall(doc_text.lower())) if t
    }
    overlap = len(query_tokens & doc_tokens) / max(len(query_tokens), 1)
    return round(0.7 * cosine + 0.3 * overlap, 4)


class InMemoryVectorStore:
    """Small in-memory vector store with cosine search."""

    def __init__(self):
        self.docs: list[dict] = []

    def add(self, doc_id: str, text: str, metadata: dict | None = None) -> None:
        self.docs.append(
            {
                "id": doc_id,
                "text": text,
                "metadata": metadata or {},
                "vector": embed(text),
            }
        )

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        q = embed(query)
        scored = [
            {
                "id": d["id"],
                "text": d["text"],
                "metadata": d["metadata"],
                "score": hybrid_score(query, d["text"], _cosine(q, d["vector"])),
            }
            for d in self.docs
        ]
        scored.sort(key=lambda r: r["score"], reverse=True)
        return [r for r in scored if r["score"] > 0][:top_k]

    def count(self) -> int:
        return len(self.docs)


class QdrantVectorStore:
    """Same interface backed by a Qdrant collection (remote or local)."""

    def __init__(self, url: str, collection: str = "policies"):
        from qdrant_client import QdrantClient
        from qdrant_client.models import Distance, PointStruct, VectorParams

        self.client = QdrantClient(url=url, api_key=config.QDRANT_API_KEY or None)
        self.collection = collection
        self._VectorParams = VectorParams
        self._PointStruct = PointStruct
        self._Distance = Distance
        try:
            self.client.get_collection(collection)
        except Exception:  # noqa: BLE001 - collection may not exist yet
            self.client.create_collection(
                collection_name=collection,
                vectors_config=VectorParams(size=DIM, distance=Distance.COSINE),
            )

    def add(self, doc_id: str, text: str, metadata: dict | None = None) -> None:
        import uuid

        point_id = str(uuid.uuid5(uuid.NAMESPACE_URL, doc_id))
        self.client.upsert(
            collection_name=self.collection,
            points=[
                self._PointStruct(
                    id=point_id,
                    vector=embed(text),
                    payload={"doc_id": doc_id, "text": text, **(metadata or {})},
                )
            ],
        )

    def search(self, query: str, top_k: int = 3) -> list[dict]:
        hits = self.client.search(
            collection_name=self.collection,
            query_vector=embed(query),
            limit=top_k,
        )
        results = [
            {
                "id": h.payload.get("doc_id"),
                "text": h.payload.get("text", ""),
                "metadata": {
                    k: v for k, v in h.payload.items() if k not in ("doc_id", "text")
                },
                "score": hybrid_score(query, h.payload.get("text", ""), float(h.score)),
            }
            for h in hits
        ]
        results.sort(key=lambda r: r["score"], reverse=True)
        return results

    def count(self) -> int:
        return int(self.client.count(self.collection).count)


_STORE = None


def get_vector_store():
    """Qdrant when QDRANT_URL is set, otherwise the in-memory store."""
    global _STORE
    if _STORE is not None:
        return _STORE
    if config.QDRANT_URL:
        try:
            _STORE = QdrantVectorStore(config.QDRANT_URL)
            return _STORE
        except Exception as exc:  # noqa: BLE001 - Qdrant is optional; fall back to in-memory
            print(f"[vectorstore] Qdrant unavailable ({exc}); using in-memory store.")
    _STORE = InMemoryVectorStore()
    return _STORE


def set_vector_store(store) -> None:
    """Override the vector store (used by tests)."""
    global _STORE
    _STORE = store
