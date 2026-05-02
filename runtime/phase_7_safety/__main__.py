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

from .safety import SafetyPipeline, route


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="runtime.phase_7_safety")
    p.add_argument("query", nargs="?", help="User query text.")
    p.add_argument(
        "--route-only",
        action="store_true",
        help="Run §7.1 router only — do not call retrieval or LLM.",
    )
    p.add_argument("--json", action="store_true", dest="as_json")
    p.add_argument("-v", "--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if not args.query:
        p.error("query is required (positional)")

    if args.route_only:
        decision = route(args.query)
        if args.as_json:
            json.dump(
                {
                    "allow": decision.allow,
                    "reason": decision.reason,
                    "matched_pattern": decision.matched_pattern,
                    "template_response": decision.template_response,
                },
                sys.stdout,
                ensure_ascii=False,
                indent=2,
            )
            sys.stdout.write("\n")
            return 0
        print(f"allow: {decision.allow}")
        print(f"reason: {decision.reason}")
        print(f"matched_pattern: {decision.matched_pattern}")
        if decision.template_response:
            print()
            print(decision.template_response)
        return 0

    result = SafetyPipeline().answer(args.query)
    if args.as_json:
        json.dump(result.to_dict(), sys.stdout, ensure_ascii=False, indent=2)
        sys.stdout.write("\n")
        return 0

    print(f"refused: {result.refused}  route_reason: {result.route_reason}")
    print(f"citation_url: {result.citation_url}")
    print(f"footer_date: {result.footer_date}")
    print(
        f"used_fallback: {result.used_fallback}  retried: {result.retried}  "
        f"model: {result.model}"
    )
    if result.validation_errors:
        print(f"validation_errors: {result.validation_errors}")
    print()
    print(result.answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
