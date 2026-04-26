from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

from .registry import load_registry
from .scraper import (
    DEFAULT_RATE_LIMIT_SECONDS,
    DEFAULT_RETRIES,
    DEFAULT_TIMEOUT_SECONDS,
    DEFAULT_USER_AGENT,
    make_run_id,
    scrape_all,
)


def _env_float(name: str, default: float) -> float:
    val = os.getenv(name)
    return float(val) if val else default


def _env_int(name: str, default: int) -> int:
    val = os.getenv(name)
    return int(val) if val else default


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="ingest.phase_4_0_scrape")
    p.add_argument(
        "--registry",
        default=os.getenv("INGEST_REGISTRY_PATH", "data/registry/urls.yaml"),
    )
    p.add_argument(
        "--raw-dir",
        default=os.getenv("INGEST_RAW_DIR", "data/raw"),
    )
    p.add_argument("--run-id", default=None, help="Override run_id (default: UTC timestamp).")
    p.add_argument(
        "--user-agent",
        default=os.getenv("INGEST_USER_AGENT", DEFAULT_USER_AGENT),
    )
    p.add_argument(
        "--rate-limit",
        type=float,
        default=_env_float("INGEST_RATE_LIMIT_SECONDS", DEFAULT_RATE_LIMIT_SECONDS),
    )
    p.add_argument(
        "--timeout",
        type=float,
        default=_env_float("INGEST_HTTP_TIMEOUT", DEFAULT_TIMEOUT_SECONDS),
    )
    p.add_argument(
        "--retries",
        type=int,
        default=_env_int("INGEST_HTTP_RETRIES", DEFAULT_RETRIES),
    )
    p.add_argument(
        "--min-success-ratio",
        type=float,
        default=_env_float("INGEST_MIN_SUCCESS_RATIO", 0.8),
        help="Exit non-zero if (ok / total) is below this ratio.",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    entries = load_registry(args.registry)
    if not entries:
        print("registry is empty; nothing to scrape", file=sys.stderr)
        return 2

    run_id = args.run_id or make_run_id()
    run_dir, results = scrape_all(
        entries,
        Path(args.raw_dir),
        run_id=run_id,
        user_agent=args.user_agent,
        timeout=args.timeout,
        rate_limit_seconds=args.rate_limit,
        retries=args.retries,
    )

    ok = sum(1 for r in results if r.status == "ok")
    total = len(results)
    ratio = ok / total if total else 0.0

    print(f"run_id={run_id}")
    print(f"output_dir={run_dir}")
    print(f"summary: ok={ok} failed={total - ok} total={total} ratio={ratio:.2f}")
    for r in results:
        print(f"  [{r.status}] {r.scheme_id}: {r.error or r.output_path}")

    if ratio < args.min_success_ratio:
        print(
            f"FAIL: success ratio {ratio:.2f} below threshold {args.min_success_ratio:.2f}",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
