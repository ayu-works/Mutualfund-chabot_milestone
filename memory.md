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
| Vector DB | **Chroma Cloud** (`trychroma.com`) — hosted, NOT local disk. Collection `mf_faq_chunks`, 384-dim cosine. Credentials: `CHROMA_TENANT`, `CHROMA_DATABASE`, `CHROMA_API_KEY`. |
| Embeddings | `BAAI/bge-small-en-v1.5` via `sentence-transformers` (local, 384-dim, 512 max input tokens) |
| LLM (generation) | Groq `llama-3.1-8b-instant` (env var `GROQ_API_KEY`) |
| Scheduler | GitHub Actions cron `45 3 * * *` UTC = **09:15 IST** (India has no DST) |
| API | FastAPI 0.115.5 + uvicorn — deployed on **Render** |
| UI | Next.js 14 + React 18 + Tailwind CSS (under `web/`) — deployed on **Vercel** |
| Thread store | SQLite locally (`data/threads.sqlite`); Postgres in production |
| HTTP scraping | `httpx`, `PyYAML` |

**Frozen-across-index-and-query** (changing any of these silently degrades retrieval): `EMBED_MODEL_ID`, embedding dimension (384), Chroma collection name, `CHUNK_TARGET_TOKENS`, `CHUNK_MAX_TOKENS`.

---

## 4. Repo layout

```
Docs/                                         # product requirements
  ProblemStatement.md
docs/                                         # architecture (source of truth)
  rag-architecture.md
  chunking-embedding-architecture.md
ingest/
  phase_4_0_scrape/                           # ✅ scrape Groww HTML
    registry.py  scraper.py  __main__.py
  phase_4_1_normalize/                        # ✅ extract __NEXT_DATA__ facts
    __main__.py
  phase_4_1_chunk/                            # ✅ section-aware chunker
    chunker.py  __main__.py
  phase_4_2_embed/                            # ✅ BGE embedder (incremental)
    embedder.py  __main__.py
  phase_4_3_index/                            # ✅ Chroma Cloud upsert
    indexer.py  __main__.py
runtime/
  phase_5_retrieval/                          # ✅ scheme-aware Chroma retrieval
    retriever.py  __main__.py
  phase_6_generation/                         # ✅ Groq LLM + validation
    generator.py  __main__.py
  phase_7_safety/                             # ✅ advisory/PII router + refusal
    safety.py  __main__.py
  phase_8_threads/                            # ✅ SQLite multi-thread chat store
    threads.py  __main__.py
  phase_9_api/                                # ✅ FastAPI REST server
    app.py  __main__.py
web/                                          # ✅ Next.js 14 frontend
  src/
    app/layout.tsx  globals.css
    components/
      ChatArea.tsx  MessageBubble.tsx  MessageInput.tsx
      SourceCard.tsx  Logo.tsx  ThemeToggle.tsx
    hooks/useTheme.ts
    lib/types.ts
data/
  registry/urls.yaml                          # 5 Groww HDFC URLs (committed)
  raw/, normalized/, chunks/,                 # all gitignored — regenerated
  embeddings/, structured/                    # per ingest run
.github/workflows/ingest.yml                 # daily cron + workflow_dispatch
requirements.txt
.env.example
.gitignore
```

---

## 5. Implementation status

| Phase | Status | Entry point |
| --- | --- | --- |
| 4.0 scrape | ✅ Done, live-verified | `python -m ingest.phase_4_0_scrape -v` |
| 4.1 normalize | ✅ Implemented | `python -m ingest.phase_4_1_normalize --run-id <id>` |
| 4.1 chunk | ✅ Implemented | `python -m ingest.phase_4_1_chunk --run-id <id>` |
| 4.2 embed | ✅ Implemented | `python -m ingest.phase_4_2_embed --run-id <id>` |
| 4.3 Chroma upsert | ✅ Implemented | `python -m ingest.phase_4_3_index --run-id <id>` |
| 5 retrieval | ✅ Implemented | `python -m runtime.phase_5_retrieval "<query>"` |
| 6 generation (Groq) | ✅ Implemented | `python -m runtime.phase_6_generation "<query>"` |
| 7 safety / refusal | ✅ Implemented | `python -m runtime.phase_7_safety "<query>"` (`--route-only` to skip retrieval) |
| 8 multi-thread | ✅ Implemented | `python -m runtime.phase_8_threads {new-thread\|say\|history\|context\|list-threads}` |
| 9 FastAPI | ✅ Implemented | `python -m runtime.phase_9_api` (UI at `/ui/`, OpenAPI at `/docs`) |
| Web frontend | ✅ Implemented | `cd web && npm run dev` (port 3000) |

---

## 6. How to run locally

```bash
# 1. Backend
pip install -r requirements.txt
cp .env.example .env          # fill GROQ_API_KEY, CHROMA_TENANT, CHROMA_DATABASE, CHROMA_API_KEY

# 2. Full ingest pipeline (re-run before testing downstream phases)
python -m ingest.phase_4_0_scrape -v                   # → data/raw/<run_id>/
python -m ingest.phase_4_1_normalize --run-id <id>     # → data/normalized/<run_id>/
python -m ingest.phase_4_1_chunk --run-id <id>         # → data/chunks/<run_id>/
python -m ingest.phase_4_2_embed --run-id <id>         # → data/embeddings/<run_id>/
python -m ingest.phase_4_3_index --run-id <id>         # → upserts to Chroma Cloud

# 3. API server
python -m runtime.phase_9_api                          # http://localhost:8000

# 4. Frontend
cd web && npm install && npm run dev                   # http://localhost:3000
```

### Ingest CLI flags (phase 4.0)

`--registry`, `--raw-dir`, `--run-id`, `--user-agent`, `--rate-limit`, `--timeout`, `--retries`, `--min-success-ratio`. All have env-var equivalents — see `.env.example`.

---

## 7. API endpoints (phase 9)

| Method | Path | Description |
| --- | --- | --- |
| GET | `/` | JSON pointers to docs, UI, health |
| GET | `/health` | Liveness check |
| POST | `/threads` | Create a new chat thread |
| GET | `/threads` | List threads (filter by `session_key`) |
| GET | `/threads/{id}/messages` | Fetch thread history |
| POST | `/threads/{id}/messages` | Send a message, get an answer |
| DELETE | `/threads/{id}` | Delete a thread |
| POST | `/admin/reindex` | Stub (501) — use GitHub Actions |
| GET | `/ui` | Static Next.js frontend |
| GET | `/docs` | OpenAPI docs |

`RUNTIME_API_DEBUG=1` adds latency, route reason, validation errors to responses.

---

## 8. Web frontend (Next.js 14)

Located in `web/`. Key components:
- `ChatArea.tsx` — main chat panel, thread history display
- `MessageBubble.tsx` — user/assistant message with citation and footer
- `MessageInput.tsx` — textarea + send button
- `SourceCard.tsx` — citation URL display card
- `ThemeToggle.tsx` — light/dark mode toggle
- `Logo.tsx` — app branding
- `useTheme.ts` — theme hook
- `lib/types.ts` — shared TypeScript types (`Thread`, `Message`, `ChatState`)

Build for static export: `npm run build` in `web/` (output goes to `web/out/`, served by FastAPI at `/ui`).

---

## 9. Deployment

- **Backend**: Render. Uses CPU-only torch (`--extra-index-url` for CPU wheels). Calls Render API directly. FastAPI served via uvicorn.
- **Frontend**: Vercel. Next.js static export. Calls Render backend directly (no Vercel rewrites — removed after early debugging).

---

## 10. Last verified live run

- **Date**: 2026-04-26. `run_id = 2026-04-26T142426Z`.
- **Result**: 5/5 fetched, ~1.9 MB total HTML. All HTTP 200 (Cloudflare-fronted).
- **Manifest**: per-URL `status`, `http_status`, `fetched_at`, `content_hash` (sha256), `bytes_written`, `output_path`.
- **Content sanity check** (mid-cap page, 411 KB):
  - `<title>` and meta description are real fund content.
  - `__NEXT_DATA__` JSON blob is **present** — structured facts (NAV, AUM, expense ratio, etc.) live there. Plain-HTML regex won't reach them.
  - Literal substrings present in HTML: `Expense Ratio`, `Exit Load`, `NAV`, `AUM`, `Benchmark`.
  - **Not** present as literal text: `Min SIP`, `Riskometer` — phase 4.1 extracts these from `__NEXT_DATA__` JSON.

---

## 11. Gotchas

- `data/raw/`, `data/normalized/`, `data/chunks/`, `data/embeddings/`, `data/structured/` are **gitignored** — per-run artifacts. Re-run the scraper before testing downstream phases locally. Only `data/registry/urls.yaml` is committed.
- GitHub Actions cron is **UTC** — `45 3 * * *` is 09:15 IST. Don't "fix" it.
- `min_success_ratio` defaults to 0.8 — if any 1 of 5 URLs fails, the scraper exits non-zero. Lower deliberately, not silently.
- Default User-Agent in `.env.example` has a placeholder GitHub URL — replace with the real repo URL once published.
- The Chroma collection dimension is fixed **at creation**. Switching to `bge-base-en-v1.5` (768-dim) requires a brand-new collection + full reindex.
- Generation (Groq) and embeddings (local BGE) are **independent providers** — don't conflate them. `GROQ_API_KEY` is not needed for ingest.
- FastAPI 0.115.5 has a known startup crash on `DELETE /threads/{thread_id}` that was fixed (commit `477eb28`). If you upgrade FastAPI, verify the DELETE endpoint still works.
- The frontend calls the Render API directly — there are no Next.js rewrites in `vercel.json`. Do not add them.

---

## 12. User preferences (observed)

- Prefers detailed architecture docs with explicit code-path references (filename + section number) over abstract prose.
- Prefers concise, skimmable updates with proof of verification (e.g., live run output, file listing) over narration of intent.
- Wants frozen design decisions stated up front so they aren't re-litigated mid-stream.
- Comfortable running CLIs locally; expects working examples, not just code.
