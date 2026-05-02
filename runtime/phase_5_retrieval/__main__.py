from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

# Windows consoles default to cp1252 which can't print ₹ etc. — force UTF-8.
try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

from .retriever import DEFAULT_COLLECTION, DEFAULT_TOP_K, Retriever


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="runtime.phase_5_retrieval")
    p.add_argument("query", nargs="?", help="User query text.")
    p.add_argument(
        "--top-k",
        type=int,
        default=int(os.getenv("RETRIEVAL_TOP_K", DEFAULT_TOP_K)),
    )
    p.add_argument(
        "--scheme-id",
        default=None,
        help="Override scheme resolution; pre-filter Chroma by this scheme_id.",
    )
    p.add_argument(
        "--amc",
        default=None,
        help="Optional AMC metadata filter.",
    )
    p.add_argument(
        "--collection",
        default=os.getenv("INGEST_CHROMA_COLLECTION", DEFAULT_COLLECTION),
    )
    p.add_argument(
        "--registry",
        default=os.getenv("INGEST_REGISTRY_PATH", "data/registry/urls.yaml"),
    )
    p.add_argument(
        "--json",
        action="store_true",
        help="Emit the full result as JSON to stdout.",
    )
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.query:
        p.error("query is required (positional)")

    retriever = Retriever(
        collection_name=args.collection,
        registry_path=args.registry,
    )
    result = retriever.retrieve(
        args.query,
        top_k=args.top_k,
        scheme_id=args.scheme_id,
        amc=args.amc,
    )

    if args.json:
        json.dump(result.to_dict(), sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0

    print(f"query: {result.query}")
    print(f"resolved_scheme_id: {result.resolved_scheme_id}")
    print(f"is_performance_query: {result.is_performance_query}")
    print(f"citation_url: {result.citation_url}")
    print(f"hits: {len(result.hits)}")
    print()
    for i, h in enumerate(result.hits[:5]):
        snippet = (h.text or "").replace("\n", " ")[:140]
        print(
            f"  #{i+1} dist={h.distance:.4f} {h.scheme_id or '-'} :: "
            f"{h.section_id or '-'}\n      {snippet}..."
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
