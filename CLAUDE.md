# CLAUDE.md

> **Read [`memory.md`](./memory.md) first.** It is the project handoff doc — what this project is, the complete tech stack, what's implemented, and known gotchas. Architecture source-of-truth lives in [`docs/rag-architecture.md`](./docs/rag-architecture.md) and [`docs/chunking-embedding-architecture.md`](./docs/chunking-embedding-architecture.md).

## Quick orientation

This is a **fully implemented** facts-only mutual fund FAQ assistant (RAG). All backend phases (4.0–9) and the Next.js frontend (`web/`) are complete. The backend runs on **Render**, the frontend on **Vercel**.

## Key decisions (frozen — don't re-litigate without user approval)

| Concern | Decision |
|---|---|
| Vector DB | **Chroma Cloud** (`trychroma.com`) — NOT local disk. Collection `mf_faq_chunks`, 384-dim cosine. |
| Embeddings | `BAAI/bge-small-en-v1.5` via `sentence-transformers` (local, 384-dim) |
| LLM | Groq `llama-3.1-8b-instant` (`GROQ_API_KEY`) |
| Ingest schedule | GitHub Actions `45 3 * * *` UTC = 09:15 IST |
| API | FastAPI + uvicorn on Render |
| Frontend | Next.js 14 + React 18 + Tailwind in `web/` deployed on Vercel |
| Thread store | SQLite locally; Postgres in production |

## Architecture docs

- `docs/rag-architecture.md` — canonical pipeline (phases 4–9), retrieval, generation, safety, threads, API
- `docs/chunking-embedding-architecture.md` — chunk/embed contract (token budgets, idempotency, vector payload)
- `Docs/ProblemStatement.md` — product requirements
