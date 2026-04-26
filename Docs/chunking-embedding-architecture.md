# Chunking & Embedding Architecture

Companion document to [`rag-architecture.md`](./rag-architecture.md). Covers the implementation-level contract for **phase 4.1 (chunk + enrich)** and **phase 4.2 (embed)** of the ingestion pipeline. The output of this phase is consumed by **phase 4.3 (local Chroma upsert)**.

Scope: HTML-only corpus (5 Groww HDFC scheme pages). PDF-aware extensions are noted but out of scope for the initial build.

---

## 1. Position in the pipeline

```
[scrape]                    raw HTML per URL per run
   │                        data/raw/<run_id>/<scheme_slug>.html
   ▼
[normalize]                 cleaned text + table-preserving sections
   │                        data/normalized/<run_id>/<scheme_slug>.json
   ▼
[chunk]   ←  THIS DOC §3    chunk records (text + metadata, no vectors)
   │                        data/chunks/<run_id>/chunks.jsonl
   ▼
[embed]   ←  THIS DOC §4    chunk records + 384-dim vectors
   │                        data/embeddings/<run_id>/embeddings.jsonl
   ▼
[index 4.3]                 upsert into Chroma (data/chroma/)
```

Each stage writes a self-contained artifact under a `run_id` so the next stage can be re-run idempotently without re-doing prior work.

---

## 2. Input contract (from normalize)

The normalize stage emits one JSON file per scheme:

```json
{
  "scheme_id": "hdfc-mid-cap-fund-direct-growth",
  "scheme_name": "HDFC Mid Cap Fund Direct Growth",
  "amc": "HDFC Mutual Fund",
  "source_url": "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth",
  "source_type": "groww_scheme_page",
  "fetched_at": "2026-04-26T03:45:00Z",
  "raw_content_hash": "sha256:…",
  "sections": [
    {
      "section_id": "overview",
      "section_title": "Fund Overview",
      "kind": "prose",
      "text": "HDFC Mid Cap Fund is an open-ended equity scheme…"
    },
    {
      "section_id": "key-metrics",
      "section_title": "Key Metrics",
      "kind": "table",
      "text": "| Metric | Value |\n| --- | --- |\n| NAV | ₹… |\n…",
      "table_html": "<table>…</table>"
    }
  ]
}
```

Notes:
- `kind` ∈ `{prose, table, list}`. The chunker uses this to decide splitting policy (§3.2).
- The normalizer is responsible for stripping nav/footer/ads and for serializing tables as Markdown (text) **and** keeping the original `table_html` for debugging.
- Numeric facts (NAV, expense ratio, AUM, min SIP, rating) are also extracted into the **structured facts store** (`data/structured/<run_id>/scheme_facts.json`) per §3.4 of the main architecture doc — independent of chunking.

---

## 3. Chunking

### 3.1 Goals

- **Preserve numeric facts**: keep table rows together so a single chunk contains both the label ("Expense Ratio") and the value ("0.52%").
- **Preserve citation atomicity**: every chunk maps to exactly one `source_url`. No cross-document chunks.
- **Stay within the embedding model's input window**: BAAI/bge-small-en-v1.5 has a **512-token max**; we target 300–450 tokens per chunk to leave headroom for the query prefix and tokenizer variance.
- **Keep retrieval clean**: avoid over-fragmenting prose (causes redundant near-duplicate hits) and avoid mega-chunks (causes vague embeddings).

### 3.2 Splitting policy by `kind`

| `kind` | Policy |
| --- | --- |
| `prose` | Recursive-character split on `\n\n` → `\n` → `. ` → ` `, with target ~400 tokens and 10–15% overlap. |
| `table` | **One chunk per table** if ≤ 450 tokens. If larger, split by row-groups (header repeated in each chunk). Never mid-row. |
| `list` | Treat as prose, but prefer to keep contiguous bullet groups in the same chunk. |

The chunker reads `section_title` and prepends it to the chunk text (e.g. `"## Key Metrics\n\n| NAV | ₹… |"`) so retrieval still finds the chunk for queries that mention the section name.

### 3.3 Token counting

- Use the **`BAAI/bge-small-en-v1.5` tokenizer** (loaded once via `transformers.AutoTokenizer.from_pretrained(...)`) — not a generic GPT tokenizer. Counting against the same tokenizer the model uses is the only safe way to enforce the 512 budget.
- Reserve **24 tokens** for the BGE query prefix at runtime (`"Represent this sentence: "`); enforce a hard cap of **488 tokens per chunk** post-prefix.

### 3.4 Overlap

- Prose: 10–15% overlap (≈ 40–60 tokens), aligned to sentence boundaries when possible.
- Tables: **no overlap** — overlapping rows would double-count numeric facts.

### 3.5 Chunk identity & idempotency

Each chunk gets a deterministic `chunk_id`:

```
chunk_id = sha1(source_url || "::" || section_id || "::" || chunk_index || "::" || normalized_text_hash)[:16]
```

- Same input → same `chunk_id` → idempotent upsert into Chroma.
- `normalized_text_hash` is `sha256(chunk_text)` — short-circuits embedding when content is unchanged across runs (§4.3 below).

### 3.6 Chunk record shape (output of phase 4.1)

`data/chunks/<run_id>/chunks.jsonl`, one JSON object per line:

```json
{
  "chunk_id": "a1b2c3d4e5f6a7b8",
  "chunk_text": "## Key Metrics\n\n| NAV | ₹… |\n| Expense Ratio | 0.52% |…",
  "chunk_text_hash": "sha256:…",
  "token_count": 312,
  "metadata": {
    "source_url": "https://groww.in/mutual-funds/hdfc-mid-cap-fund-direct-growth",
    "source_type": "groww_scheme_page",
    "scheme_id": "hdfc-mid-cap-fund-direct-growth",
    "scheme_name": "HDFC Mid Cap Fund Direct Growth",
    "amc": "HDFC Mutual Fund",
    "section_id": "key-metrics",
    "section_title": "Key Metrics",
    "kind": "table",
    "chunk_index": 0,
    "fetched_at": "2026-04-26T03:45:00Z",
    "run_id": "2026-04-26T0345Z"
  }
}
```

### 3.7 De-duplication

Within a run, if two chunks share `chunk_text_hash` (e.g. a boilerplate disclaimer that appears on every scheme page), keep the first occurrence and merge `metadata.source_urls` into a list. Across runs, `chunk_id` collisions are upserts, not duplicates.

---

## 4. Embedding

### 4.1 Model

| Setting | Value |
| --- | --- |
| Model id | `BAAI/bge-small-en-v1.5` |
| Library | `sentence-transformers` (loads via `transformers` under the hood) |
| Dimension | **384** |
| Max input tokens | 512 |
| Distance metric (Chroma) | cosine |
| Normalization | L2-normalize embeddings at write time (`normalize_embeddings=True`) — required for cosine in Chroma to behave like dot product |
| Query prefix | `"Represent this sentence: "` — applied **only at query time**, not at index time (BGE asymmetric retrieval convention) |

Upgrade path: when corpus grows (>50 schemes or AMFI/SEBI added), switch to `BAAI/bge-base-en-v1.5` (768-dim). The collection dimension is fixed at creation, so an upgrade requires **a new collection** + full reindex.

### 4.2 Batching

- Batch size: **32** chunks per forward pass on CPU; **64** on a GPU runner (`ubuntu-latest` has CPU only — stick with 32).
- Sort the batch by `token_count` ascending so each batch has minimal padding waste.
- Stream batches; never load the full corpus into memory.

### 4.3 Incremental embedding

Compute embeddings only for chunks whose `chunk_text_hash` is **not** present in the previous run's manifest:

```
prev_hashes = load(data/embeddings/<previous_run_id>/manifest.json).hashes
new_chunks  = [c for c in chunks if c.chunk_text_hash not in prev_hashes]
reused      = [c for c in chunks if c.chunk_text_hash in prev_hashes]
```

- Embed `new_chunks` only.
- Copy embeddings for `reused` chunks from the previous artifact (no model call).
- Daily run on an unchanged corpus → near-zero embedding cost.

### 4.4 Output (input to phase 4.3)

`data/embeddings/<run_id>/embeddings.jsonl`:

```json
{
  "chunk_id": "a1b2c3d4e5f6a7b8",
  "embedding": [0.0123, -0.0456, …],
  "embedding_dim": 384,
  "embedding_model_id": "BAAI/bge-small-en-v1.5",
  "chunk_text_hash": "sha256:…"
}
```

Plus a `manifest.json` summarizing the run:

```json
{
  "run_id": "2026-04-26T0345Z",
  "embedding_model_id": "BAAI/bge-small-en-v1.5",
  "embedding_dim": 384,
  "chunk_count": 142,
  "new_count": 7,
  "reused_count": 135,
  "created_at": "2026-04-26T03:48:11Z",
  "hashes": ["…", "…"]
}
```

---

## 5. Vector payload contract (handover to Chroma §4.3)

For each chunk, phase 4.3 writes:

| Chroma field | Source |
| --- | --- |
| `id` | `chunk_id` (§3.5) |
| `embedding` | `embeddings.jsonl.embedding` |
| `document` | `chunks.jsonl.chunk_text` |
| `metadata` | `chunks.jsonl.metadata` (filterable subset) |

Filterable metadata keys: `source_url`, `scheme_id`, `scheme_name`, `amc`, `source_type`, `fetched_at`, `chunk_index`, `section_title`, `run_id`, `chunk_text_hash`. All scalar — Chroma does not filter on lists.

---

## 6. Configuration

Environment variables (loaded from `.env` locally, GitHub Actions secrets/vars in CI):

| Variable | Default | Purpose |
| --- | --- | --- |
| `INGEST_RAW_DIR` | `data/raw/` | Where scraper writes HTML. |
| `INGEST_NORMALIZED_DIR` | `data/normalized/` | Where normalizer writes section JSON. |
| `INGEST_CHUNKS_DIR` | `data/chunks/` | Where this stage writes chunk JSONL. |
| `INGEST_EMBEDDINGS_DIR` | `data/embeddings/` | Where this stage writes vectors. |
| `INGEST_CHROMA_DIR` | `data/chroma/` | Phase 4.3 persistent client path. |
| `INGEST_CHROMA_COLLECTION` | `mf_faq_chunks` | Collection name (per environment). |
| `EMBED_MODEL_ID` | `BAAI/bge-small-en-v1.5` | Frozen across index + query. |
| `EMBED_BATCH_SIZE` | `32` | CPU default. |
| `CHUNK_TARGET_TOKENS` | `400` | Target chunk size. |
| `CHUNK_MAX_TOKENS` | `488` | Hard cap (post query-prefix headroom). |
| `CHUNK_OVERLAP_TOKENS` | `48` | ~12% of target. |

`EMBED_MODEL_ID`, `CHUNK_TARGET_TOKENS`, `CHUNK_MAX_TOKENS`, and Chroma dimension **must remain frozen** between index build and query — changing any of them silently degrades retrieval quality.

---

## 7. CLI surface

Each stage is independently runnable for debugging:

```bash
python -m ingest.phase_4_1_chunk    --run-id 2026-04-26T0345Z
python -m ingest.phase_4_2_embed    --run-id 2026-04-26T0345Z
python -m ingest.phase_4_3_index    --run-id 2026-04-26T0345Z
```

Each command:
1. Reads its input directory for the given `run_id`.
2. Writes its output artifact + `manifest.json`.
3. Exits non-zero on any per-document failure that drops below a configurable quality threshold (default: ≥ 80% of registry URLs must produce ≥ 1 chunk).

The GitHub Actions workflow chains these three commands sequentially after scrape + normalize. See §4.0 of the main architecture doc.

---

## 8. Failure modes and mitigations

| Failure | Mitigation |
| --- | --- |
| Tokenizer mismatch (e.g. switched to a different model accidentally) | `manifest.json` records `embedding_model_id`; phase 4.3 refuses to upsert if it disagrees with Chroma collection metadata. |
| Empty `sections[]` from normalize (page changed structure) | Chunker emits zero chunks for that scheme, marks failure in run manifest, retriever excludes that scheme until re-fixed (§4.2 of main doc). |
| Embedding drift on retry | `chunk_text_hash` makes embedding deterministic given identical text; reused chunks copy the prior vector verbatim. |
| Chunk exceeds 512 tokens (encoding artifact) | Hard truncation at `CHUNK_MAX_TOKENS`; logged as a warning. |
| Boilerplate dominates retrieval | De-dup by `chunk_text_hash` (§3.7) + scheme metadata filters at query time (§5.2 of main doc). |

---

## 9. Future extensions (not in initial build)

- **PDF chunking** (KIM, SID, factsheets): page-aware splitting, table extraction via `pdfplumber` or `unstructured`, OCR only if required.
- **Hybrid retrieval**: BM25 sidecar index over the same chunks for keyword-heavy queries (e.g. exact ISIN). Build alongside Chroma; merge at query time.
- **Cross-encoder re-ranker**: `BAAI/bge-reranker-base` over the top-20 dense hits — orthogonal to chunking, but benefits from the same chunk shape.
- **Larger embeddings**: `bge-base-en-v1.5` (768-dim) when corpus growth makes recall the bottleneck. Requires new Chroma collection.
