from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

from .indexer import DEFAULT_COLLECTION, index_run

load_dotenv()


def _latest_run(root: Path) -> Path | None:
    if not root.exists():
        return None
    runs = [p for p in root.iterdir() if p.is_dir()]
    return max(runs, key=lambda p: p.name) if runs else None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ingest.phase_4_3_index")
    p.add_argument(
        "--chunks-dir",
        default=os.getenv("INGEST_CHUNKS_DIR", "data/chunks"),
    )
    p.add_argument(
        "--embeddings-dir",
        default=os.getenv("INGEST_EMBEDDINGS_DIR", "data/embeddings"),
    )
    p.add_argument(
        "--collection",
        default=os.getenv("INGEST_CHROMA_COLLECTION", DEFAULT_COLLECTION),
    )
    p.add_argument(
        "--run-id",
        default=None,
        help="Run id (default: latest under --embeddings-dir).",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    embeddings_root = Path(args.embeddings_dir)
    if args.run_id:
        embeddings_run_dir = embeddings_root / args.run_id
    else:
        embeddings_run_dir = _latest_run(embeddings_root) or Path()
    if not embeddings_run_dir.exists():
        print(f"embeddings run dir not found: {embeddings_run_dir}", file=sys.stderr)
        return 2

    chunks_run_dir = Path(args.chunks_dir) / embeddings_run_dir.name
    if not chunks_run_dir.exists():
        print(f"matching chunks run dir not found: {chunks_run_dir}", file=sys.stderr)
        return 2

    try:
        stats = index_run(
            chunks_run_dir,
            embeddings_run_dir,
            collection_name=args.collection,
        )
    except RuntimeError as exc:
        print(f"FAIL: {exc}", file=sys.stderr)
        return 2

    print(f"run_id={stats.run_id}")
    print(f"collection={stats.collection_name}")
    print(f"chroma_tenant={stats.chroma_tenant}")
    print(f"chroma_database={stats.chroma_database}")
    print(f"embedding_model_id={stats.embedding_model_id}")
    print(
        f"summary: chunks={stats.chunk_count} upserted={stats.upserted_count} "
        f"skipped_unchanged={stats.skipped_unchanged}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
