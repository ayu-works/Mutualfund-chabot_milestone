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

from .threads import ThreadedChat, ThreadStore, expand_query


def _print_json(obj) -> None:
    json.dump(obj, sys.stdout, ensure_ascii=False, indent=2, default=str)
    sys.stdout.write("\n")


def cmd_new_thread(args) -> int:
    store = ThreadStore(db_path=args.db)
    t = store.create_thread(session_key=args.session_key)
    if args.as_json:
        _print_json(t.to_dict())
    else:
        print(t.thread_id)
    return 0


def cmd_say(args) -> int:
    chat = ThreadedChat(store=ThreadStore(db_path=args.db))
    result = chat.post_user_message(
        args.thread_id,
        args.message,
        use_query_expansion=not args.no_expand,
    )
    if args.as_json:
        _print_json(result.to_dict())
        return 0
    print(f"refused: {result.refused}  route_reason: {result.route_reason}")
    print(f"citation_url: {result.citation_url}")
    print(f"footer_date: {result.footer_date}")
    print(
        f"used_fallback: {result.used_fallback}  retried: {result.retried}  "
        f"model: {result.model}"
    )
    print()
    print(result.answer)
    return 0


def cmd_history(args) -> int:
    store = ThreadStore(db_path=args.db)
    msgs = store.history(args.thread_id)
    if args.as_json:
        _print_json([m.to_dict() for m in msgs])
        return 0
    for m in msgs:
        print(f"[{m.timestamp}] {m.role}: {m.content}")
    return 0


def cmd_context(args) -> int:
    store = ThreadStore(db_path=args.db)
    msgs = store.recent_window(args.thread_id, max_turns=args.max_turns)
    expanded = expand_query(args.thread_id, args.latest, store)
    if args.as_json:
        _print_json(
            {
                "window": [m.to_dict() for m in msgs],
                "expanded_query": expanded,
            }
        )
        return 0
    print(f"window ({len(msgs)} messages):")
    for m in msgs:
        print(f"  [{m.timestamp}] {m.role}: {m.content[:120]}")
    print()
    print(f"expanded_query: {expanded}")
    return 0


def cmd_list_threads(args) -> int:
    store = ThreadStore(db_path=args.db)
    threads = store.list_threads(session_key=args.session_key, limit=args.limit)
    if args.as_json:
        _print_json([t.to_dict() for t in threads])
        return 0
    for t in threads:
        print(f"{t.thread_id}  {t.created_at}  session={t.session_key or '-'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="runtime.phase_8_threads")
    p.add_argument("--db", default=None, help="Override THREAD_DB_PATH.")
    p.add_argument("--json", action="store_true", dest="as_json")
    p.add_argument("-v", "--verbose", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    s_new = sub.add_parser("new-thread", help="Create a new thread.")
    s_new.add_argument("--session-key", default=None)
    s_new.set_defaults(func=cmd_new_thread)

    s_say = sub.add_parser("say", help="Post a user message and get an assistant reply.")
    s_say.add_argument("thread_id")
    s_say.add_argument("message")
    s_say.add_argument("--no-expand", action="store_true")
    s_say.set_defaults(func=cmd_say)

    s_hist = sub.add_parser("history", help="Show all messages for a thread.")
    s_hist.add_argument("thread_id")
    s_hist.set_defaults(func=cmd_history)

    s_ctx = sub.add_parser("context", help="Inspect last-N window + expanded query.")
    s_ctx.add_argument("thread_id")
    s_ctx.add_argument("latest", help="Hypothetical latest user message.")
    s_ctx.add_argument("--max-turns", type=int, default=None)
    s_ctx.set_defaults(func=cmd_context)

    s_list = sub.add_parser("list-threads")
    s_list.add_argument("--session-key", default=None)
    s_list.add_argument("--limit", type=int, default=50)
    s_list.set_defaults(func=cmd_list_threads)

    args = p.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
