from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


DEFAULT_COLLECTION = "mf_faq_chunks"
EMBEDDING_DIM = 384


@dataclass
class IndexRunStats:
    run_id: str
    collection_name: str
    chroma_tenant: str
    chroma_database: str
    embedding_model_id: str
    embedding_dim: int
    chunk_count: int
    upserted_count: int
    skipped_unchanged: int


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_jsonl(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as fh:
        return [json.loads(line) for line in fh if line.strip()]


def _embedding_manifest(embeddings_run_dir: Path) -> dict[str, Any]:
    p = embeddings_run_dir / "manifest.json"
    if not p.exists():
        raise FileNotFoundError(f"missing embeddings manifest: {p}")
    return json.loads(p.read_text(encoding="utf-8"))


def _existing_hashes(collection: Any, ids: list[str]) -> dict[str, str]:
    """Return {chunk_id: chunk_text_hash} for ids already present in the collection."""
    if not ids:
        return {}
    out: dict[str, str] = {}
    for start in range(0, len(ids), 1000):
        batch = ids[start : start + 1000]
        got = collection.get(ids=batch, include=["metadatas"])
        for i, meta in zip(got.get("ids") or [], got.get("metadatas") or []):
            if meta and "chunk_text_hash" in meta:
                out[i] = meta["chunk_text_hash"]
    return out


def _require_env(name: str) -> str:
    val = os.getenv(name)
    if not val:
        raise RuntimeError(
            f"{name} is required (Chroma Cloud credential). Set it in .env or CI secrets."
        )
    return val


def index_run(
    chunks_run_dir: Path,
    embeddings_run_dir: Path,
    *,
    collection_name: str = DEFAULT_COLLECTION,
    tenant: str | None = None,
    database: str | None = None,
    api_key: str | None = None,
) -> IndexRunStats:
    """Upsert chunk vectors + metadata into Chroma Cloud.

    Reads chunks.jsonl + embeddings.jsonl from the given run directories,
    joins by chunk_id, and upserts into the Cloud collection. Skips writes
    for chunks whose chunk_text_hash already matches the stored metadata.
    """
    import chromadb  # type: ignore

    chunks = _read_jsonl(chunks_run_dir / "chunks.jsonl")
    embeddings = _read_jsonl(embeddings_run_dir / "embeddings.jsonl")
    emb_manifest = _embedding_manifest(embeddings_run_dir)

    embedding_model_id = emb_manifest.get("embedding_model_id", "")
    embedding_dim = emb_manifest.get("embedding_dim", EMBEDDING_DIM)
    if embedding_dim != EMBEDDING_DIM:
        raise ValueError(
            f"embedding_dim mismatch: manifest={embedding_dim} expected={EMBEDDING_DIM}"
        )

    by_id_emb = {e["chunk_id"]: e for e in embeddings}
    missing = [c["chunk_id"] for c in chunks if c["chunk_id"] not in by_id_emb]
    if missing:
        raise ValueError(
            f"{len(missing)} chunk_id(s) missing embeddings; first: {missing[0]}"
        )

    tenant = tenant or _require_env("CHROMA_TENANT")
    database = database or _require_env("CHROMA_DATABASE")
    api_key = api_key or _require_env("CHROMA_API_KEY")

    log.info("connecting to Chroma Cloud (tenant=%s database=%s)", tenant, database)
    client = chromadb.CloudClient(
        tenant=tenant,
        database=database,
        api_key=api_key,
    )
    collection = client.get_or_create_collection(
        name=collection_name,
        metadata={
            "hnsw:space": "cosine",
            "embedding_model_id": embedding_model_id,
            "embedding_dim": embedding_dim,
        },
    )

    coll_meta = collection.metadata or {}
    coll_model = coll_meta.get("embedding_model_id")
    coll_dim = coll_meta.get("embedding_dim")
    if coll_model and coll_model != embedding_model_id:
        raise ValueError(
            f"collection embedding_model_id mismatch: collection={coll_model} run={embedding_model_id}"
        )
    if coll_dim and int(coll_dim) != int(embedding_dim):
        raise ValueError(
            f"collection embedding_dim mismatch: collection={coll_dim} run={embedding_dim}"
        )

    ids = [c["chunk_id"] for c in chunks]
    prior_hashes = _existing_hashes(collection, ids)

    upsert_ids: list[str] = []
    upsert_embeddings: list[list[float]] = []
    upsert_documents: list[str] = []
    upsert_metadatas: list[dict[str, Any]] = []
    skipped = 0
    run_id = chunks_run_dir.name

    for c in chunks:
        cid = c["chunk_id"]
        new_hash = c["chunk_text_hash"]
        if prior_hashes.get(cid) == new_hash:
            skipped += 1
            continue
        meta = dict(c["metadata"])
        meta["chunk_text_hash"] = new_hash
        upsert_ids.append(cid)
        upsert_embeddings.append(by_id_emb[cid]["embedding"])
        upsert_documents.append(c["chunk_text"])
        upsert_metadatas.append(meta)

    if upsert_ids:
        log.info("upserting %d chunks into collection '%s'", len(upsert_ids), collection_name)
        collection.upsert(
            ids=upsert_ids,
            embeddings=upsert_embeddings,
            documents=upsert_documents,
            metadatas=upsert_metadatas,
        )
    else:
        log.info("no changes; collection already current for run %s", run_id)

    manifest = {
        "run_id": run_id,
        "phase": "4.3_index",
        "embedding_model_id": embedding_model_id,
        "embedding_dim": embedding_dim,
        "collection_name": collection_name,
        "chroma_tenant": tenant,
        "chroma_database": database,
        "chunk_count": len(chunks),
        "upserted_count": len(upsert_ids),
        "skipped_unchanged": skipped,
        "indexed_at": _now_iso(),
        "updated_at": _now_iso(),
    }
    manifest_path = embeddings_run_dir / "index_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return IndexRunStats(
        run_id=run_id,
        collection_name=collection_name,
        chroma_tenant=tenant,
        chroma_database=database,
        embedding_model_id=embedding_model_id,
        embedding_dim=embedding_dim,
        chunk_count=len(chunks),
        upserted_count=len(upsert_ids),
        skipped_unchanged=skipped,
    )
