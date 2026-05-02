from __future__ import annotations

import argparse
import json
import logging
import sys

from dotenv import load_dotenv

load_dotenv()

try:
    sys.stdout.reconfigure(encoding="utf-8")
except (AttributeError, OSError):
    pass

from runtime.phase_5_retrieval import Retriever
from .generator import Generator


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="runtime.phase_6_generation")
    p.add_argument("query", nargs="?", help="User query text.")
    p.add_argument("--top-k", type=int, default=20)
    p.add_argument("--scheme-id", default=None)
    p.add_argument("--amc", default=None)
    p.add_argument("--json", action="store_true", dest="as_json")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.query:
        p.error("query is required (positional)")

    retriever = Retriever()
    retrieval = retriever.retrieve(
        args.query,
        top_k=args.top_k,
        scheme_id=args.scheme_id,
        amc=args.amc,
    )
    gen = Generator(retriever=retriever)
    result = gen.generate(args.query, retrieval=retrieval)

    if args.as_json:
        out = result.to_dict()
        out["retrieval"] = {
            "resolved_scheme_id": retrieval.resolved_scheme_id,
            "is_performance_query": retrieval.is_performance_query,
            "citation_url": retrieval.citation_url,
            "hit_count": len(retrieval.hits),
        }
        json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0

    print(f"query: {args.query}")
    print(f"model: {result.model}")
    print(f"citation_url: {result.citation_url}")
    print(f"footer_date: {result.footer_date}")
    print(f"retried: {result.retried}  used_fallback: {result.used_fallback}")
    if result.validation_errors:
        print(f"validation_errors: {result.validation_errors}")
    print()
    print(result.answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
