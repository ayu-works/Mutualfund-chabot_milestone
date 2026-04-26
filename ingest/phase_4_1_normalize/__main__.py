from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from ..phase_4_0_scrape.registry import load_registry
from .normalizer import normalize_all


def _latest_run(raw_root: Path) -> Path | None:
    if not raw_root.exists():
        return None
    runs = [p for p in raw_root.iterdir() if p.is_dir()]
    if not runs:
        return None
    return max(runs, key=lambda p: p.name)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ingest.phase_4_1_normalize")
    p.add_argument(
        "--raw-dir",
        default=os.getenv("INGEST_RAW_DIR", "data/raw"),
    )
    p.add_argument(
        "--out-dir",
        default=os.getenv("INGEST_NORMALIZED_DIR", "data/normalized"),
    )
    p.add_argument(
        "--facts-dir",
        default=os.getenv("INGEST_STRUCTURED_DIR", "data/structured"),
    )
    p.add_argument(
        "--registry",
        default=os.getenv("INGEST_REGISTRY_PATH", "data/registry/urls.yaml"),
        help="URL registry, used for AMC and canonical scheme names.",
    )
    p.add_argument(
        "--run-id",
        default=None,
        help="Raw run_id under --raw-dir (default: latest directory).",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    raw_root = Path(args.raw_dir)
    if args.run_id:
        raw_run_dir = raw_root / args.run_id
    else:
        raw_run_dir = _latest_run(raw_root) or Path()
    if not raw_run_dir.exists():
        print(f"raw run dir not found: {raw_run_dir}", file=sys.stderr)
        return 2

    entries = load_registry(args.registry)
    amc = entries[0].amc if entries else "Unknown"
    name_overrides = {e.scheme_id: e.scheme_name for e in entries}

    normalized_dir, structured_dir, results, facts = normalize_all(
        raw_run_dir,
        Path(args.out_dir),
        Path(args.facts_dir),
        amc=amc,
        scheme_name_overrides=name_overrides,
    )

    ok = sum(1 for r in results if r.status == "ok")
    total = len(results)
    print(f"run_id={raw_run_dir.name}")
    print(f"normalized_dir={normalized_dir}")
    print(f"structured_dir={structured_dir}")
    print(f"summary: ok={ok} failed={total - ok} total={total}")
    for r in results:
        warns = f" warnings={r.facts_warnings}" if r.facts_warnings else ""
        detail = r.error or f"sections={r.section_count}{warns}"
        print(f"  [{r.status}] {r.scheme_id}: {detail}")
    return 0 if ok == total and total > 0 else (1 if ok < total else 2)


if __name__ == "__main__":
    raise SystemExit(main())
