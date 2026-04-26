from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from .chunker import (
    DEFAULT_MAX_TOKENS,
    DEFAULT_MODEL_ID,
    DEFAULT_OVERLAP_TOKENS,
    DEFAULT_TARGET_TOKENS,
    chunk_all,
)


def _env_int(name: str, default: int) -> int:
    val = os.getenv(name)
    return int(val) if val else default


def _latest_run(root: Path) -> Path | None:
    if not root.exists():
        return None
    runs = [p for p in root.iterdir() if p.is_dir()]
    return max(runs, key=lambda p: p.name) if runs else None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ingest.phase_4_1_chunk")
    p.add_argument(
        "--normalized-dir",
        default=os.getenv("INGEST_NORMALIZED_DIR", "data/normalized"),
    )
    p.add_argument(
        "--out-dir",
        default=os.getenv("INGEST_CHUNKS_DIR", "data/chunks"),
    )
    p.add_argument(
        "--run-id",
        default=None,
        help="Normalized run_id (default: latest under --normalized-dir).",
    )
    p.add_argument(
        "--model-id",
        default=os.getenv("EMBED_MODEL_ID", DEFAULT_MODEL_ID),
    )
    p.add_argument(
        "--target-tokens",
        type=int,
        default=_env_int("CHUNK_TARGET_TOKENS", DEFAULT_TARGET_TOKENS),
    )
    p.add_argument(
        "--max-tokens",
        type=int,
        default=_env_int("CHUNK_MAX_TOKENS", DEFAULT_MAX_TOKENS),
    )
    p.add_argument(
        "--overlap-tokens",
        type=int,
        default=_env_int("CHUNK_OVERLAP_TOKENS", DEFAULT_OVERLAP_TOKENS),
    )
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    normalized_root = Path(args.normalized_dir)
    if args.run_id:
        normalized_run_dir = normalized_root / args.run_id
    else:
        normalized_run_dir = _latest_run(normalized_root) or Path()
    if not normalized_run_dir.exists():
        print(f"normalized run dir not found: {normalized_run_dir}", file=sys.stderr)
        return 2

    chunks_run_dir, stats = chunk_all(
        normalized_run_dir,
        Path(args.out_dir),
        model_id=args.model_id,
        target_tokens=args.target_tokens,
        max_tokens=args.max_tokens,
        overlap_tokens=args.overlap_tokens,
    )

    print(f"run_id={stats.run_id}")
    print(f"chunks_dir={chunks_run_dir}")
    print(
        f"summary: schemes ok={stats.ok_schemes} failed={stats.failed_schemes} "
        f"total_chunks={stats.total_chunks} truncated={stats.truncated_chunks}"
    )
    for r in stats.results:
        detail = r.error or f"chunks={r.chunk_count}"
        print(f"  [{r.status}] {r.scheme_id}: {detail}")
    return 0 if stats.failed_schemes == 0 and stats.total_schemes > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
