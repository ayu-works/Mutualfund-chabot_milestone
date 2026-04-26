from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from .embedder import DEFAULT_BATCH_SIZE, DEFAULT_MODEL_ID, embed_run


def _env_int(name: str, default: int) -> int:
    val = os.getenv(name)
    return int(val) if val else default


def _latest_run(root: Path) -> Path | None:
    if not root.exists():
        return None
    runs = [p for p in root.iterdir() if p.is_dir()]
    return max(runs, key=lambda p: p.name) if runs else None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ingest.phase_4_2_embed")
    p.add_argument(
        "--chunks-dir",
        default=os.getenv("INGEST_CHUNKS_DIR", "data/chunks"),
    )
    p.add_argument(
        "--out-dir",
        default=os.getenv("INGEST_EMBEDDINGS_DIR", "data/embeddings"),
    )
    p.add_argument(
        "--run-id",
        default=None,
        help="Chunks run_id (default: latest under --chunks-dir).",
    )
    p.add_argument(
        "--model-id",
        default=os.getenv("EMBED_MODEL_ID", DEFAULT_MODEL_ID),
    )
    p.add_argument(
        "--batch-size",
        type=int,
        default=_env_int("EMBED_BATCH_SIZE", DEFAULT_BATCH_SIZE),
    )
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    chunks_root = Path(args.chunks_dir)
    if args.run_id:
        chunks_run_dir = chunks_root / args.run_id
    else:
        chunks_run_dir = _latest_run(chunks_root) or Path()
    if not chunks_run_dir.exists():
        print(f"chunks run dir not found: {chunks_run_dir}", file=sys.stderr)
        return 2

    stats = embed_run(
        chunks_run_dir,
        Path(args.out_dir),
        model_id=args.model_id,
        batch_size=args.batch_size,
    )

    print(f"run_id={stats.run_id}")
    print(f"out_path={stats.out_path}")
    print(
        f"summary: chunks={stats.chunk_count} new={stats.new_count} "
        f"reused={stats.reused_count} dim={stats.embedding_dim}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
