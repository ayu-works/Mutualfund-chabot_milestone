"""Phase 5 — Retrieval Layer.

See docs/rag-architecture.md §5.

* §5.1 Query preprocessing: lowercase normalize + scheme resolution via the
  URL registry (dictionary match on distinctive scheme-name tokens).
* §5.2 Retrieval mechanics: BGE query embedding (with the asymmetric query
  prefix per chunking-embedding-architecture.md §4.1), Chroma Cloud query,
  optional metadata filter (`scheme_id`, `amc`), merge by `source_url`.
* §5.3 Single-citation rule: pick the highest-confidence chunk's
  `source_url` as the citation; tie-break by newer `fetched_at`.
* §5.4 Performance questions: this layer never computes returns. It just
  surfaces the chunks; phase 6 handles the answer template. The flag
  `is_performance_query` is set so phase 6 can short-circuit if desired.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


DEFAULT_COLLECTION = "mf_faq_chunks"
DEFAULT_TOP_K = 20
EMBED_MODEL_ID_DEFAULT = "BAAI/bge-small-en-v1.5"
QUERY_PREFIX = "Represent this sentence: "

# Heuristic stop-words for scheme resolution (§5.1). Tokens shared across every
# registry entry — keeping them would mean "HDFC fund" matches everything.
_SCHEME_STOP_TOKENS = {
    "hdfc", "fund", "direct", "growth", "plan", "scheme", "mutual",
}

# Phrases that signal a performance / returns / comparison ask. Matches §5.4
# and overlaps with the safety router (§7) — both layers should agree.
_PERFORMANCE_PATTERNS = re.compile(
    r"\b(returns?|cagr|xirr|performance|outperform(?:ed|ing)?|"
    r"compare(?:d|s)?|vs\.?|versus|past\s+(?:year|month|1y|3y|5y|10y))\b",
    re.IGNORECASE,
)


@dataclass
class RetrievalHit:
    chunk_id: str
    text: str
    source_url: str
    scheme_id: str | None
    scheme_name: str | None
    section_id: str | None
    section_title: str | None
    fetched_at: str | None
    distance: float


@dataclass
class RetrievalResult:
    query: str
    resolved_scheme_id: str | None
    is_performance_query: bool
    citation_url: str | None
    hits: list[RetrievalHit] = field(default_factory=list)
    merged_context: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "resolved_scheme_id": self.resolved_scheme_id,
            "is_performance_query": self.is_performance_query,
            "citation_url": self.citation_url,
            "merged_context": self.merged_context,
            "hits": [asdict(h) for h in self.hits],
        }


# ---------- §5.1 query preprocessing ----------


def _load_registry_lookup(registry_path: str | Path) -> list[tuple[str, str, set[str]]]:
    """Return [(scheme_id, scheme_name, distinctive_tokens), ...] from urls.yaml."""
    import yaml  # local import to avoid hard dep at import time

    path = Path(registry_path)
    if not path.exists():
        return []
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    out: list[tuple[str, str, set[str]]] = []
    for item in raw.get("urls", []):
        sid = item["scheme_id"]
        name = item["scheme_name"]
        tokens = {
            t for t in re.findall(r"[a-z0-9]+", name.lower())
            if t and t not in _SCHEME_STOP_TOKENS
        }
        out.append((sid, name, tokens))
    return out


def resolve_scheme(query: str, lookup: list[tuple[str, str, set[str]]]) -> str | None:
    """Return scheme_id whose distinctive tokens best match the query, or None."""
    q_tokens = set(re.findall(r"[a-z0-9]+", query.lower()))
    best_score = 0
    best_id: str | None = None
    for sid, _name, tokens in lookup:
        if not tokens:
            continue
        score = len(tokens & q_tokens)
        # Require at least one distinctive token AND score >= half the
        # distinctive tokens for that scheme — keeps "equity" alone from
        # weakly matching the equity fund.
        if score >= 1 and score >= max(1, (len(tokens) + 1) // 2):
            if score > best_score:
                best_score = score
                best_id = sid
    return best_id


def is_performance_query(query: str) -> bool:
    return bool(_PERFORMANCE_PATTERNS.search(query))


# ---------- §5.2 retrieval mechanics ----------


class Retriever:
    """Cached BGE encoder + Chroma Cloud collection handle."""

    def __init__(
        self,
        *,
        collection_name: str | None = None,
        model_id: str | None = None,
        registry_path: str | None = None,
        tenant: str | None = None,
        database: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.collection_name = collection_name or os.getenv(
            "INGEST_CHROMA_COLLECTION", DEFAULT_COLLECTION
        )
        self.model_id = model_id or os.getenv("EMBED_MODEL_ID", EMBED_MODEL_ID_DEFAULT)
        self.registry_path = registry_path or os.getenv(
            "INGEST_REGISTRY_PATH", "data/registry/urls.yaml"
        )
        self._tenant = tenant or _require_env("CHROMA_TENANT")
        self._database = database or _require_env("CHROMA_DATABASE")
        self._api_key = api_key or _require_env("CHROMA_API_KEY")

        self._collection = None
        self._model = None
        self._lookup: list[tuple[str, str, set[str]]] | None = None

    def _ensure_collection(self) -> Any:
        if self._collection is None:
            import chromadb  # type: ignore

            client = chromadb.CloudClient(
                tenant=self._tenant,
                database=self._database,
                api_key=self._api_key,
            )
            self._collection = client.get_collection(self.collection_name)
        return self._collection

    def _ensure_model(self) -> Any:
        if self._model is None:
            from sentence_transformers import SentenceTransformer  # type: ignore

            log.info("loading BGE model %s", self.model_id)
            self._model = SentenceTransformer(self.model_id)
        return self._model

    def _ensure_lookup(self) -> list[tuple[str, str, set[str]]]:
        if self._lookup is None:
            self._lookup = _load_registry_lookup(self.registry_path)
        return self._lookup

    def _embed_query(self, query: str) -> list[float]:
        model = self._ensure_model()
        prefixed = QUERY_PREFIX + query
        vec = model.encode([prefixed], normalize_embeddings=True)[0]
        return [float(x) for x in vec.tolist()]

    def retrieve(
        self,
        query: str,
        *,
        top_k: int = DEFAULT_TOP_K,
        scheme_id: str | None = None,
        amc: str | None = None,
        merge_context_chars: int = 4000,
    ) -> RetrievalResult:
        if not query.strip():
            return RetrievalResult(
                query=query,
                resolved_scheme_id=None,
                is_performance_query=False,
                citation_url=None,
            )

        lookup = self._ensure_lookup()
        resolved_scheme_id = scheme_id or resolve_scheme(query, lookup)
        perf = is_performance_query(query)

        where: dict[str, Any] | None = None
        clauses = []
        if resolved_scheme_id:
            clauses.append({"scheme_id": resolved_scheme_id})
        if amc:
            clauses.append({"amc": amc})
        if len(clauses) == 1:
            where = clauses[0]
        elif len(clauses) > 1:
            where = {"$and": clauses}

        qvec = self._embed_query(query)
        coll = self._ensure_collection()
        res = coll.query(
            query_embeddings=[qvec],
            n_results=top_k,
            where=where,
        )

        hits = self._build_hits(res)

        # §5.3 — pick a single citation.
        citation_url = self._select_citation(hits)

        # §5.2 step 4 — merge text of chunks sharing the citation URL.
        merged_context = self._merge_context(hits, citation_url, merge_context_chars)

        return RetrievalResult(
            query=query,
            resolved_scheme_id=resolved_scheme_id,
            is_performance_query=perf,
            citation_url=citation_url,
            hits=hits,
            merged_context=merged_context,
        )

    @staticmethod
    def _build_hits(res: dict[str, Any]) -> list[RetrievalHit]:
        ids = (res.get("ids") or [[]])[0]
        docs = (res.get("documents") or [[]])[0]
        metas = (res.get("metadatas") or [[]])[0]
        dists = (res.get("distances") or [[]])[0]
        out: list[RetrievalHit] = []
        for cid, doc, meta, dist in zip(ids, docs, metas, dists):
            meta = meta or {}
            out.append(
                RetrievalHit(
                    chunk_id=cid,
                    text=doc or "",
                    source_url=meta.get("source_url", ""),
                    scheme_id=meta.get("scheme_id"),
                    scheme_name=meta.get("scheme_name"),
                    section_id=meta.get("section_id"),
                    section_title=meta.get("section_title"),
                    fetched_at=meta.get("fetched_at"),
                    distance=float(dist),
                )
            )
        return out

    @staticmethod
    def _select_citation(hits: list[RetrievalHit]) -> str | None:
        if not hits:
            return None
        # Primary rule: best-scoring chunk's source_url.
        best = hits[0]
        # Conflict rule: if the runner-up is very close in score but on a
        # different source_url, prefer the newer fetched_at snapshot.
        if len(hits) >= 2 and hits[1].source_url != best.source_url:
            margin = hits[1].distance - best.distance
            if margin < 0.02:  # near-tie
                if (hits[1].fetched_at or "") > (best.fetched_at or ""):
                    return hits[1].source_url
        return best.source_url or None

    @staticmethod
    def _merge_context(
        hits: list[RetrievalHit], citation_url: str | None, char_budget: int
    ) -> str:
        if not citation_url:
            return ""
        parts: list[str] = []
        used = 0
        for h in hits:
            if h.source_url != citation_url:
                continue
            if used + len(h.text) > char_budget and parts:
                break
            parts.append(h.text)
            used += len(h.text)
        return "\n\n".join(parts)


# ---------- helpers ----------


def _require_env(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(
            f"{name} is required (Chroma Cloud credential). "
            "Set it in .env or runtime environment."
        )
    return val


# Module-level convenience: lazy singleton retriever for one-shot calls.
_default_retriever: Retriever | None = None


def retrieve(
    query: str,
    *,
    top_k: int = DEFAULT_TOP_K,
    scheme_id: str | None = None,
    amc: str | None = None,
) -> RetrievalResult:
    global _default_retriever
    if _default_retriever is None:
        _default_retriever = Retriever()
    return _default_retriever.retrieve(
        query, top_k=top_k, scheme_id=scheme_id, amc=amc
    )
