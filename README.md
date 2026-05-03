# Mutual Fund FAQ Assistant

> **Facts-only. No investment advice.**

A closed-book RAG chatbot that answers factual questions about 5 HDFC mutual fund schemes using data scraped from Groww. Every answer is ≤3 sentences, cites exactly one source URL, and includes a last-updated date. Advisory queries are politely refused.

---

## Selected AMC and Schemes

**AMC**: HDFC Mutual Fund (sourced via Groww scheme pages)

| Scheme | Category |
|---|---|
| HDFC Mid Cap Fund — Direct Growth | Mid Cap |
| HDFC Equity Fund — Direct Growth | Flexi Cap |
| HDFC Focused Fund — Direct Growth | Focused |
| HDFC ELSS Tax Saver Fund — Direct Plan Growth | ELSS / Tax Saving |
| HDFC Large Cap Fund — Direct Growth | Large Cap |

---

## Architecture Overview (RAG)

```
Groww pages (5 URLs)
        │
        ▼
┌─────────────────────────────────────────────────┐
│  INGEST PIPELINE  (GitHub Actions, daily 09:15 IST) │
│                                                 │
│  Phase 4.0 Scrape  → HTML files                 │
│  Phase 4.1 Normalize → structured JSON facts    │
│  Phase 4.1 Chunk   → 300–450 token text chunks  │
│  Phase 4.2 Embed   → 384-dim BGE vectors        │
│  Phase 4.3 Index   → Chroma Cloud upsert        │
└─────────────────────────────────────────────────┘
        │
        ▼ Chroma Cloud (hosted vector DB)
        │
┌─────────────────────────────────────────────────┐
│  RUNTIME PIPELINE  (FastAPI on Render)          │
│                                                 │
│  Phase 5 Retrieval → scheme-aware Chroma query  │
│  Phase 6 Generation → Groq LLM (llama-3.1-8b)  │
│  Phase 7 Safety    → advisory/PII router        │
│  Phase 8 Threads   → SQLite multi-thread store  │
│  Phase 9 API       → FastAPI REST endpoints     │
└─────────────────────────────────────────────────┘
        │
        ▼
┌─────────────────────┐
│  FRONTEND (Vercel)  │
│  Next.js 14 + React │
│  + Tailwind CSS     │
└─────────────────────┘
```

**Key technology choices:**

| Layer | Technology |
|---|---|
| Embeddings | `BAAI/bge-small-en-v1.5` (local, 384-dim, via `sentence-transformers`) |
| Vector DB | Chroma Cloud — hosted, 384-dim cosine similarity |
| LLM | Groq `llama-3.1-8b-instant` |
| API | FastAPI 0.115.5 + uvicorn |
| Frontend | Next.js 14 + React 18 + Tailwind CSS |
| Ingest schedule | GitHub Actions cron (`45 3 * * *` UTC = 09:15 IST) |
| Thread storage | SQLite (local) / Postgres (production) |

---

## Setup Instructions

### Prerequisites

- Python 3.11+
- Node.js 18+ (for the frontend)
- A [Chroma Cloud](https://trychroma.com) account (free tier works)
- A [Groq](https://console.groq.com) API key (free tier works)

### 1. Clone and install

```bash
git clone <repo-url>
cd mf-faq-assistant

pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
```

Edit `.env` and fill in:

```env
# Chroma Cloud — get from trychroma.com console
CHROMA_TENANT=your-tenant-id
CHROMA_DATABASE=your-database-name
CHROMA_API_KEY=your-chroma-api-key

# Groq — get from console.groq.com
GROQ_API_KEY=your-groq-api-key
```

All other values in `.env.example` have sensible defaults.

### 3. Run the ingest pipeline

```bash
# Scrape HTML from Groww
python -m ingest.phase_4_0_scrape -v

# Note the run_id printed (e.g. 2026-04-26T142426Z), then:
RUN_ID=<run_id>

python -m ingest.phase_4_1_normalize --run-id $RUN_ID
python -m ingest.phase_4_1_chunk --run-id $RUN_ID
python -m ingest.phase_4_2_embed --run-id $RUN_ID
python -m ingest.phase_4_3_index --run-id $RUN_ID
```

Ingest runs automatically every day at 09:15 IST via GitHub Actions (`.github/workflows/ingest.yml`).

### 4. Start the API server

```bash
python -m runtime.phase_9_api
# → http://localhost:8000
# → OpenAPI docs: http://localhost:8000/docs
```

### 5. Start the frontend (optional)

```bash
cd web
npm install
npm run dev
# → http://localhost:3000
```

Or build for production:

```bash
cd web
npm run build    # outputs to web/out/, served by FastAPI at /ui
```

---

## API Reference

| Method | Endpoint | Description |
|---|---|---|
| GET | `/health` | Liveness check |
| POST | `/threads` | Create a new chat thread |
| GET | `/threads` | List all threads |
| GET | `/threads/{id}/messages` | Get conversation history |
| POST | `/threads/{id}/messages` | Send a message, receive an answer |
| DELETE | `/threads/{id}` | Delete a thread |
| GET | `/docs` | Interactive OpenAPI documentation |
| GET | `/ui` | Web frontend |

### Example: ask a question

```bash
# Create a thread
curl -X POST http://localhost:8000/threads
# → {"thread_id": "abc123", ...}

# Ask a question
curl -X POST http://localhost:8000/threads/abc123/messages \
  -H "Content-Type: application/json" \
  -d '{"content": "What is the expense ratio of HDFC Mid Cap Fund?"}'
```

Response:

```json
{
  "assistant_message": "The expense ratio of HDFC Mid Cap Fund Direct Plan is 0.77% per annum. ...\nLast updated from sources: 2026-04-26",
  "citation_url": "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth",
  "footer_date": "2026-04-26"
}
```

### Debug mode

Set `RUNTIME_API_DEBUG=1` to include latency, route decision, and validation errors in responses. Keep this off in production.

---

## Disclaimer

**Facts-only. No investment advice.**

This assistant provides factual information about mutual fund schemes sourced from public AMC and aggregator pages. It does not provide investment recommendations, performance comparisons, or return calculations. For investment decisions, consult a SEBI-registered investment advisor.

---

## Known Limitations

- **Corpus is narrow**: Only 5 HDFC schemes from Groww. Queries about other AMCs or schemes will not find relevant results.
- **Data freshness**: Content is refreshed daily at 09:15 IST. NAV and other dynamic values may be up to 24 hours stale.
- **Performance queries redirected**: Queries about returns or performance comparisons are deliberately refused and redirected to official factsheets.
- **No chart or image data**: The assistant operates on text only. Fund performance charts are not accessible.
- **`__NEXT_DATA__` dependency**: Structured facts (NAV, AUM, expense ratio, riskometer) are extracted from Groww's embedded JSON blob. If Groww changes its page structure, ingest will need updating.
- **Chroma dimension is fixed**: The collection was created with 384-dim vectors (`bge-small-en-v1.5`). Switching to a larger embedding model requires a full reindex with a new collection.
- **English only**: The assistant does not support queries in Hindi or other languages.

---

## Project Structure

```
ingest/               # data ingestion pipeline (phases 4.0–4.3)
runtime/              # query pipeline (phases 5–9) + FastAPI server
web/                  # Next.js 14 frontend
data/
  registry/urls.yaml  # 5 source URLs (the only committed data file)
docs/                 # architecture specifications
Docs/                 # product requirements
.github/workflows/    # CI/CD (daily ingest cron)
requirements.txt      # Python dependencies
.env.example          # environment variable template
```

---

## CLI Quick Reference

```bash
# Query the full pipeline from the command line
python -m runtime.phase_7_safety "What is the exit load for HDFC ELSS?"

# Route-only (check if advisory/PII, no retrieval)
python -m runtime.phase_7_safety --route-only "Should I invest in this fund?"

# Retrieval only
python -m runtime.phase_5_retrieval "expense ratio HDFC large cap"

# Thread management
python -m runtime.phase_8_threads new-thread
python -m runtime.phase_8_threads say <thread_id> "What is the minimum SIP?"
python -m runtime.phase_8_threads history <thread_id>
python -m runtime.phase_8_threads list-threads
```
