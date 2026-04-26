from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

log = logging.getLogger(__name__)


DEFAULT_MODEL_ID = "BAAI/bge-small-en-v1.5"
DEFAULT_BATCH_SIZE = 32
EMBEDDING_DIM = 384


@dataclass
class EmbedRunStats:
    run_id: str
    embedding_model_id: str
    embedding_dim: int
    chunk_count: int
    new_count: int
    reused_count: int
    out_path: Path


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _read_chunks(chunks_jsonl: Path) -> list[dict[str, Any]]:
    chunks: list[dict[str, Any]] = []
    with chunks_jsonl.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            chunks.append(json.loads(line))
    return chunks


def _previous_run_dir(embeddings_root: Path, current_run_id: str) -> Path | None:
    if not embeddings_root.exists():
        return None
    candidates = [
        p
        for p in embeddings_root.iterdir()
        if p.is_dir() and p.name < current_run_id and (p / "manifest.json").exists()
    ]
    return max(candidates, key=lambda p: p.name) if candidates else None


def _load_prev_embeddings_by_hash(prev_dir: Path) -> dict[str, list[float]]:
    out: dict[str, list[float]] = {}
    emb_path = prev_dir / "embeddings.jsonl"
    if not emb_path.exists():
        return out
    with emb_path.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            rec = json.loads(line)
            h = rec.get("chunk_text_hash")
            if h and h not in out:
                out[h] = rec["embedding"]
    return out


def _embed_batches(
    chunks: list[dict[str, Any]],
    *,
    model_id: str,
    batch_size: int,
) -> dict[str, list[float]]:
    """Embed `chunks` (sorted ascending by token_count) and return {chunk_id: vector}."""
    if not chunks:
        return {}

    from sentence_transformers import SentenceTransformer  # type: ignore

    log.info("loading embedding model %s", model_id)
    model = SentenceTransformer(model_id)

    sorted_chunks = sorted(chunks, key=lambda c: c.get("token_count", 0))
    out: dict[str, list[float]] = {}
    for start in range(0, len(sorted_chunks), batch_size):
        batch = sorted_chunks[start : start + batch_size]
        texts = [c["chunk_text"] for c in batch]
        log.info("embedding batch %d-%d", start, start + len(batch))
        vectors = model.encode(
            texts,
            batch_size=batch_size,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        for c, vec in zip(batch, vectors):
            out[c["chunk_id"]] = [float(x) for x in vec.tolist()]
    return out


def embed_run(
    chunks_run_dir: Path,
    embeddings_root: Path,
    *,
    model_id: str = DEFAULT_MODEL_ID,
    batch_size: int = DEFAULT_BATCH_SIZE,
) -> EmbedRunStats:
    """Embed every chunk in `chunks_run_dir/chunks.jsonl`.

    Reuses prior embeddings when chunk_text_hash matches the immediate
    predecessor run under `embeddings_root`. Writes embeddings.jsonl and
    manifest.json under embeddings_root/<run_id>/.
    """
    chunks_jsonl = chunks_run_dir / "chunks.jsonl"
    if not chunks_jsonl.exists():
        raise FileNotFoundError(f"chunks file not found: {chunks_jsonl}")

    run_id = chunks_run_dir.name
    out_dir = Path(embeddings_root) / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    chunks = _read_chunks(chunks_jsonl)

    prev_dir = _previous_run_dir(Path(embeddings_root), run_id)
    prev_by_hash: dict[str, list[float]] = {}
    if prev_dir is not None:
        prev_by_hash = _load_prev_embeddings_by_hash(prev_dir)
        log.info(
            "found previous embeddings run %s with %d hashes",
            prev_dir.name, len(prev_by_hash),
        )

    new_chunks: list[dict[str, Any]] = []
    reused: list[tuple[dict[str, Any], list[float]]] = []
    for c in chunks:
        h = c["chunk_text_hash"]
        prev_vec = prev_by_hash.get(h)
        if prev_vec is not None and len(prev_vec) == EMBEDDING_DIM:
            reused.append((c, prev_vec))
        else:
            new_chunks.append(c)

    log.info("chunks: total=%d new=%d reused=%d", len(chunks), len(new_chunks), len(reused))

    new_vectors = _embed_batches(new_chunks, model_id=model_id, batch_size=batch_size)

    out_path = out_dir / "embeddings.jsonl"
    hashes: list[str] = []
    written = 0
    with out_path.open("w", encoding="utf-8") as out_fh:
        for c, vec in reused:
            rec = {
                "chunk_id": c["chunk_id"],
                "embedding": vec,
                "embedding_dim": EMBEDDING_DIM,
                "embedding_model_id": model_id,
                "chunk_text_hash": c["chunk_text_hash"],
            }
            out_fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            hashes.append(c["chunk_text_hash"])
            written += 1
        for c in new_chunks:
            vec = new_vectors[c["chunk_id"]]
            if len(vec) != EMBEDDING_DIM:
                raise ValueError(
                    f"unexpected embedding dim for {c['chunk_id']}: "
                    f"got {len(vec)} expected {EMBEDDING_DIM}"
                )
            rec = {
                "chunk_id": c["chunk_id"],
                "embedding": vec,
                "embedding_dim": EMBEDDING_DIM,
                "embedding_model_id": model_id,
                "chunk_text_hash": c["chunk_text_hash"],
            }
            out_fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            hashes.append(c["chunk_text_hash"])
            written += 1

    manifest = {
        "run_id": run_id,
        "phase": "4.2_embed",
        "embedding_model_id": model_id,
        "embedding_dim": EMBEDDING_DIM,
        "chunk_count": written,
        "new_count": len(new_chunks),
        "reused_count": len(reused),
        "previous_run_id": prev_dir.name if prev_dir else None,
        "created_at": _now_iso(),
        "hashes": hashes,
    }
    (out_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )

    return EmbedRunStats(
        run_id=run_id,
        embedding_model_id=model_id,
        embedding_dim=EMBEDDING_DIM,
        chunk_count=written,
        new_count=len(new_chunks),
        reused_count=len(reused),
        out_path=out_path,
    )


def iter_embeddings(embeddings_jsonl: Path) -> Iterable[dict[str, Any]]:
    with embeddings_jsonl.open(encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                yield json.loads(line)
