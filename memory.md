# Project Handoff — Mutual Fund FAQ Assistant

> **For a future Claude session opening this repo cold.** Read this file first. It is the entry point. The architecture docs are the source of truth for design; this file tells you where to start, what's done, and what's next.

---

## 1. What this project is

A **facts-only mutual fund FAQ assistant** built as a closed-book RAG system over **5 HDFC scheme pages on Groww**. Answers must be ≤3 sentences, include exactly one citation URL from an allowlist, and end with `Last updated from sources: <date>`. Advisory queries ("should I invest…") are refused with an educational link. Multi-thread chat is supported. No PII handling.

Full requirements: [`Docs/ProblemStatement.md`](./Docs/ProblemStatement.md).

---

## 2. Read first (in priority order)

1. [`Docs/ProblemStatement.md`](./Docs/ProblemStatement.md) — product requirements.
2. [`docs/rag-architecture.md`](./docs/rag-architecture.md) — **canonical architecture**. Do not redesign without explicit user approval.
3. [`docs/chunking-embedding-architecture.md`](./docs/chunking-embedding-architecture.md) — implementation contract for phases 4.1–4.3 (file shapes, token budgets, batching, idempotency, vector payload).

---

## 3. Frozen tech stack

These are decided. Do not re-litigate without user approval.

| Layer | Choice |
| --- | --- |
| Vector DB | Chroma `PersistentClient` on disk under `data/chroma/`, **384-dim, cosine** |
| Embeddings | `BAAI/bge-small-en-v1.5` via `sentence-transformers` (local, 384-dim, 512 max input tokens) |
| LLM (generation) | Groq `llama-3.1-8b-instant` (env var `GROQ_API_KEY`) |
| Scheduler | GitHub Actions cron `45 3 * * *` UTC = **09:15 IST** (India has no DST) |
| API | FastAPI + uvicorn |
| UI | Next.js (under `web/`, **not yet built**) |
| Threads | SQLite locally; Postgres in production |
| HTTP scraping | `httpx`, `PyYAML` |

**Frozen-across-index-and-query** (changing any of these silently degrades retrieval): `EMBED_MODEL_ID`, embedding dimension (384), Chroma collection name, `CHUNK_TARGET_TOKENS`, `CHUNK_MAX_TOKENS`.

---

## 4. Repo layout

```
Docs/                                     # requirements
  ProblemStatement.md
docs/                                     # architecture (source of truth)
  rag-architecture.md
  chunking-embedding-architecture.md
ingest/
  phase_4_0_scrape/                       # IMPLEMENTED + verified live
    registry.py  scraper.py  __main__.py
  phase_4_1_chunk/                        # placeholder package only
  phase_4_2_embed/                        # placeholder package only
  phase_4_3_index/                        # placeholder package only
runtime/
  phase_5_retrieval/                      # placeholder package only
  phase_6_generation/                     # placeholder package only
  phase_7_safety/                         # placeholder package only
  phase_8_threads/                        # placeholder package only
  phase_9_api/                            # placeholder package only
data/
  registry/urls.yaml                      # 5 Groww HDFC URLs (committed)
  raw/, normalized/, chunks/,             # all gitignored — regenerated
  embeddings/, chroma/, structured/         per ingest run
.github/workflows/ingest.yml              # cron + workflow_dispatch
requirements.txt
.env.example
.gitignore
```

---

## 5. Implementation status

| Phase | Status | Entry point |
| --- | --- | --- |
| 4.0 scrape | ✅ Done, live-verified | `python -m ingest.phase_4_0_scrape -v` |
| 4.1 normalize + chunk | ⬜ Not started — placeholder package | (build next) |
| 4.2 embed | ⬜ Not started — placeholder package | (to build) |
| 4.3 Chroma upsert | ⬜ Not started — placeholder package | (to build) |
| 5 retrieval | ⬜ Placeholder | (to build) |
| 6 generation (Groq) | ⬜ Placeholder | (to build) |
| 7 safety / refusal | ⬜ Placeholder | (to build) |
| 8 multi-thread | ⬜ Placeholder | (to build) |
| 9 FastAPI | ⬜ Placeholder | (to build) |

Placeholder packages exist as empty `__init__.py` files so future phases drop into a known module path without restructuring imports.

---

## 6. How to run

```bash
pip install -r requirements.txt
cp .env.example .env                       # fill GROQ_API_KEY when phase 6 lands
python -m ingest.phase_4_0_scrape -v       # writes data/raw/<run_id>/{*.html, manifest.json}
```

CLI flags: `--registry`, `--raw-dir`, `--run-id`, `--user-agent`, `--rate-limit`, `--timeout`, `--retries`, `--min-success-ratio`. All have env-var equivalents — see `.env.example`.

CI: `.github/workflows/ingest.yml` runs the same command daily at 09:15 IST and on `workflow_dispatch`. It uploads `data/raw/<run_id>/` as an artifact.

---

## 7. Last verified live run

- **Date**: 2026-04-26. `run_id = 2026-04-26T142426Z`.
- **Result**: 5/5 fetched, ~1.9 MB total HTML. All HTTP 200 (Cloudflare-fronted).
- **Manifest**: per-URL `status`, `http_status`, `fetched_at`, `content_hash` (sha256), `bytes_written`, `output_path`.
- **Content sanity check** (mid-cap page, 411 KB):
  - `<title>` and meta description are real fund content.
  - `__NEXT_DATA__` JSON blob is **present** — that is where structured facts (NAV, AUM, expense ratio, etc.) live. **Plain-HTML regex won't reach them.**
  - Literal substrings present in HTML: `Expense Ratio`, `Exit Load`, `NAV`, `AUM`, `Benchmark`.
  - **Not** present as literal text: `Min SIP`, `Riskometer` — phase 4.1 must extract these from the `__NEXT_DATA__` JSON, not regex over rendered HTML.

---

## 8. Next task — phase 4.1 (normalize + structured-fact extraction)

Per [`docs/chunking-embedding-architecture.md`](./docs/chunking-embedding-architecture.md) §2.

**Inputs**:
- `data/raw/<run_id>/<scheme_slug>.html`
- `data/raw/<run_id>/manifest.json` (for `fetched_at`, `content_hash`, source `url`)

**Outputs**:
- `data/normalized/<run_id>/<scheme_slug>.json` — sections array, each `{ section_id, section_title, kind: prose|table|list, text, table_html? }`. Strip nav/footer/ads. Tables as Markdown **and** keep raw `table_html`.
- `data/structured/<run_id>/scheme_facts.json` — typed fields per scheme (NAV+currency+as_of, minimum_sip+frequency, fund_size/aum, expense_ratio+plan, rating+rating_kind). `null` for any field not parsed; never invent values. See `rag-architecture.md` §3.4 for the full schema.

**Implementation approach**:
1. Parse `<script id="__NEXT_DATA__" type="application/json">…</script>` first → primary source for structured fields.
2. Fall back to BeautifulSoup over rendered HTML for prose/table sections that are not in the JSON blob.
3. Token-count chunks against the BGE tokenizer (`AutoTokenizer.from_pretrained("BAAI/bge-small-en-v1.5")`), not a generic GPT tokenizer.
4. Emit a `manifest.json` per stage with counts + per-scheme parse-warning flags.
5. CLI shape: `python -m ingest.phase_4_1_chunk --run-id <id>` (matches the convention used by phase 4.0).

Likely deps to add to `requirements.txt`: `beautifulsoup4`, `lxml`, `transformers`.

---

## 9. Gotchas

- `data/raw/`, `data/normalized/`, `data/chunks/`, `data/embeddings/`, `data/chroma/`, `data/structured/` are **gitignored** — they are per-run artifacts. Re-run the scraper before testing downstream phases locally. Only `data/registry/urls.yaml` is committed.
- GitHub Actions cron is **UTC** — `45 3 * * *` is 09:15 IST. Don't "fix" it.
- `min_success_ratio` defaults to 0.8 — if any 1 of 5 URLs fails, the scraper exits non-zero and CI marks the run failed. Lower it deliberately, not silently.
- Default User-Agent in `.env.example` has a placeholder GitHub URL — replace with the real repo URL once published, and override via `INGEST_USER_AGENT`.
- Architecture docs use placeholder hrefs like `[chunking-embedding-architecture.md](about:blank)` in some tables. The filename is what matters; ignore the `about:blank`.
- The Chroma collection dimension is fixed **at creation**. Switching to `bge-base-en-v1.5` (768-dim) requires a brand-new collection + full reindex.
- Generation (Groq) and embeddings (local BGE) are **independent providers** — don't conflate them. `GROQ_API_KEY` is not needed for ingest.

---

## 10. User preferences (observed)

- Prefers detailed architecture docs with explicit code-path references (filename + section number) over abstract prose.
- Prefers concise, skimmable updates with proof of verification (e.g., live run output, file listing) over narration of intent.
- Wants frozen design decisions stated up front so they aren't re-litigated mid-stream.
- Comfortable running CLIs locally; expects working examples, not just code.
