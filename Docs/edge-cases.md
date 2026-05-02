# Edge Cases — Mutual Fund FAQ Assistant

Derived from `problemStatement.md` and `rag-architecture.md`. Each case has an ID, the input stimulus, the expected behaviour, and which layer owns the response.

---

## 1. Safety & Refusal Router (§7.1)

| ID | Input | Expected behaviour |
|----|-------|--------------------|
| S-01 | "Should I invest in HDFC Mid Cap Fund?" | Refused. Polite refusal + AMFI educational link. No retrieval. |
| S-02 | "Which fund is better — HDFC Mid Cap or HDFC Large Cap?" | Refused. Comparative query detected (`which … better`). |
| S-03 | "What is the best HDFC mutual fund for me?" | Refused. Ranking + personal-fit pattern. |
| S-04 | "Recommend a fund for long-term wealth creation." | Refused. `recommend` keyword matched. |
| S-05 | "I am 35 years old, which fund should I pick?" | Refused. Personal-situation cue (`I am 35`). |
| S-06 | "Will this fund give 15% returns?" | Refused. Future-promise pattern (`will … return`). |
| S-07 | "Is HDFC Mid Cap a good investment?" | Refused. Opinion-seeking (`is … good investment`). |
| S-08 | "In your opinion, is HDFC ELSS worth it?" | Refused. Explicit opinion request. |
| S-09 | "HDFC Mid Cap vs HDFC Large Cap — who wins?" | Refused. `vs` pattern. |
| S-10 | "Compare HDFC Mid Cap and SBI Bluechip." | Refused. Comparison across AMCs. |
| S-11 | "How much will I earn if I invest ₹5,000 per month for 10 years?" | Refused. Return-calculation / future-promise. |
| S-12 | "Guaranteed returns on HDFC ELSS?" | Refused. `guaranteed returns` forbidden phrase. |
| S-13 | "What are the risks of HDFC Mid Cap Fund?" | **Allowed.** Factual question about riskometer/category — retrieval proceeds. |
| S-14 | "Has HDFC Mid Cap Fund ever underperformed its benchmark?" | **Refused or safe fallback.** Historical performance comparison — performance-query flag set; generation must not compute/compare returns, must redirect to scheme page. |
| S-15 | "What is the 3-year CAGR of HDFC Equity Fund?" | Refused / redirected. `cagr` performance pattern; respond with scheme URL only. |
| S-16 | "" (empty string) | Refused immediately. Empty-query guard. |
| S-17 | "   " (whitespace only) | Refused. Stripped to empty. |
| S-18 | "???!!!" (only punctuation) | Router allows (no advisory match); retrieval returns no hits; fallback response. |

---

## 2. PII Detection (§7.3)

| ID | Input | Expected behaviour |
|----|-------|--------------------|
| P-01 | "My PAN is ABCDE1234F, what is the exit load?" | Refused. PAN detected. Query not forwarded to retrieval or LLM. Redacted in any log line. |
| P-02 | "Aadhaar 9999 8888 7777 — can I invest?" | Refused. Aadhaar pattern matched. |
| P-03 | "Call me at 9876543210 for more info." | Refused. Indian mobile number detected. |
| P-04 | "Email me at user@example.com the NAV." | Refused. Email pattern matched. |
| P-05 | "OTP: 482910 — what is the minimum SIP?" | Refused. OTP pattern matched. |
| P-06 | "My portfolio number is 12345678 — expense ratio?" | **Allowed.** 8-digit number alone does not match Aadhaar (12 digits) or PAN format. Retrieval proceeds. |
| P-07 | Query containing PII embedded mid-sentence | Refused regardless of position. Regex scans full query string. |
| P-08 | PII in session_key field | session_key is stored as-is (non-PII key only per spec). API accepts it; no PII check on session_key at the API layer (responsibility is the caller's). Document this limitation. |

---

## 3. Retrieval — Query & Scheme Resolution (§5.1 / §5.2)

| ID | Input | Expected behaviour |
|----|-------|--------------------|
| R-01 | "What is the expense ratio of HDFC Mid Cap Fund?" | scheme_id resolved to `hdfc-mid-cap-fund-direct-growth`; Chroma pre-filtered; top hit returns key-metrics chunk. |
| R-02 | "expense ratio" (no scheme name) | scheme_id = None; broad search across all 5 schemes; citation = highest-scoring chunk's URL. |
| R-03 | "What is the expense ratio of HDFC Midcap?" (typo) | `midcap` may not score ≥ half of distinctive tokens for mid-cap scheme; scheme_id likely None; broad search. Answer may still be correct from top hit. |
| R-04 | "What is the exit load for HDFC Small Cap?" (scheme not in registry) | scheme_id = None (no match); broad search returns nothing relevant; fallback response with closest scheme URL or "cannot find in indexed sources". |
| R-05 | "What is the NAV?" with no scheme context | scheme_id = None; retrieves top hit across all schemes; citation = one scheme URL; answer may be NAV of whichever scheme scores highest. |
| R-06 | Query where top-20 hits all have distance > 0.9 (no good match) | Low-confidence hits still returned; generation uses them; may produce fallback if context is empty after merge. |
| R-07 | "What is the minimum SIP for all 5 HDFC funds?" | scheme_id = None; merged context from top-k will likely cover multiple schemes; generator must cite exactly one URL — may only answer for one scheme; limitation to document. |
| R-08 | "HDFC" alone as query | Scores weakly across all schemes (stop-token); scheme_id = None; broad retrieval. |
| R-09 | Query in Hindi: "न्यूनतम SIP क्या है?" | scheme_id resolution fails (non-ASCII tokens); BGE encodes multilingual text; retrieval may still return relevant chunks but quality degrades. |
| R-10 | Query longer than 512 BGE tokens | Prefixed query truncated by BGE tokenizer at encode time; retrieval degrades silently. Should be caught upstream or logged. |
| R-11 | Two chunks from different schemes score within 0.02 of each other (near-tie) | `_select_citation` applies conflict rule: prefer newer `fetched_at`. |
| R-12 | Collection is empty (first boot, ingest not run) | `collection.get_collection` succeeds; `collection.query` returns zero hits; merged_context = ""; generator produces templated fallback. |
| R-13 | "What is the benchmark of HDFC Focused Fund?" | scheme_id resolved; section `key-metrics` or `overview` contains benchmark; answer includes benchmark name + citation. |
| R-14 | Follow-up thread message "What about exit load?" after asking about Mid Cap | Query expansion prepends prior user lines; expanded query includes "mid cap"; scheme resolves correctly. |
| R-15 | Follow-up with no prior context: first message in thread is "What about exit load?" | No prior user lines to expand; query sent as-is; scheme_id = None; broad retrieval. |

---

## 4. Generation & Validation (§6 / §7.2)

| ID | Scenario | Expected behaviour |
|----|----------|--------------------|
| G-01 | LLM returns answer with no URL | Validation fails (`no URL`); retry with stricter prompt. |
| G-02 | LLM returns answer with two URLs | Validation fails (`multiple URLs`); retry. If retry still fails, templated fallback. |
| G-03 | LLM returns a URL not on the allowlist | Validation fails (`URL not on allowlist`); retry. Fallback if retry fails. |
| G-04 | LLM returns 4 sentences in body | Validation fails (`too many sentences`); retry. |
| G-05 | LLM response contains "you should invest" | Validation fails (`forbidden phrase`); retry. |
| G-06 | LLM response contains "better than" | Validation fails; retry. |
| G-07 | LLM response contains "guaranteed" | Validation fails; retry. |
| G-08 | LLM passes on retry (first draft invalid, second valid) | `retried=True`, `used_fallback=False`; answer returned normally. |
| G-09 | LLM fails validation on both attempts | Templated fallback: "I cannot find this… Please refer to [scheme URL]". `used_fallback=True`. |
| G-10 | Footer line missing from LLM response | Validation fails (`missing or malformed footer`); retry. |
| G-11 | Footer date does not match cited chunk's `fetched_at` | Validation fails (`footer date does not match`); retry. |
| G-12 | `GROQ_API_KEY` not set | Generator returns templated fallback immediately without calling API. `validation_errors=["GROQ_API_KEY missing"]`. |
| G-13 | Groq API returns HTTP 429 (rate limit) | `httpx.HTTPStatusError` raised; propagates as uncaught exception from `_call_groq`; should be caught and treated as fallback. **Gap: currently unhandled.** |
| G-14 | Groq API timeout (30 s exceeded) | `httpx.TimeoutException`; same gap as G-13. |
| G-15 | Retrieved context has `citation_url = None` | `pack_context` returns `("", None)`; generator returns fallback immediately. |
| G-16 | Chunk text contains ₹ symbol and Unicode | Sentence splitter and URL regex should handle non-ASCII correctly; validate footer and URL extraction still work. |
| G-17 | Answer body is exactly 3 sentences | Passes validation. Boundary condition. |
| G-18 | Answer body is exactly 1 sentence + footer | Passes validation (`sentences=1`, footer stripped before counting). |

---

## 5. Citation & URL Integrity (§5.3 / §6.2 / §7.2)

| ID | Scenario | Expected behaviour |
|----|----------|--------------------|
| C-01 | `source_url` stored with trailing slash; allowlist entry has no trailing slash | `_normalize_url` strips trailing slash before comparison; match succeeds. |
| C-02 | `source_url` stored as HTTP; allowlist has HTTPS | `_normalize_url` lowercases scheme; mismatch if protocol differs — **allowlist and stored URLs must use the same scheme**. |
| C-03 | URL contains a fragment (`#section`) | `_normalize_url` drops fragment; comparison uses path only. |
| C-04 | LLM appends punctuation to URL (`https://groww.in/…,`) | `urls[0].rstrip(".,);")` strips trailing punctuation before allowlist check. |
| C-05 | Chunk metadata has empty `source_url` | `RetrievalHit.source_url = ""`; `_select_citation` returns `None`; fallback triggered. |
| C-06 | All 5 registry URLs changed (registry updated but index not rebuilt) | Retriever returns old URLs; those URLs are now off the allowlist; validation fails on every answer; all responses are fallbacks until re-ingest runs. |

---

## 6. Ingest Pipeline (Phases 4.0–4.3)

| ID | Scenario | Expected behaviour |
|----|----------|--------------------|
| I-01 | One of 5 Groww URLs returns HTTP 404 | Scraper marks that scheme `failed`; continues with remaining 4; `ok/total = 0.8 = min_success_ratio`; exits code 0 (threshold met). One scheme missing from index until next run. |
| I-02 | One URL returns HTTP 200 but empty body | Scraper marks `failed` (`empty body` error). Same as I-01. |
| I-03 | Groww returns HTTP 200 but no `__NEXT_DATA__` script tag | Normalizer raises `ValueError("__NEXT_DATA__ script not found")`; scheme marked `failed` in normalize manifest; zero chunks for that scheme. |
| I-04 | `__NEXT_DATA__` present but none of the tried server-data keys exist and no known fact keys in `pageProps` | `_server_data` raises `ValueError`; scheme `failed` in normalize. |
| I-05 | `mfServerSideData` present but `nav` key is null/missing | `nav` field = `None` in `SchemeFacts`; `warnings = ["missing:nav"]`; key-metrics table shows `NAV = —`. Ingest continues. |
| I-06 | All structured facts null (Groww restructured their data entirely) | All `SchemeFacts` fields null; all warnings emitted; `key-metrics` table is all `—`; chunks still indexed (with empty metric values); retrieval returns them but answers will be unhelpful. |
| I-07 | HTML file on disk is not valid UTF-8 | `html_path.read_text(encoding="utf-8")` raises `UnicodeDecodeError`; caught by bare `except Exception`; scheme marked `failed`. |
| I-08 | `CHUNK_MAX_TOKENS` exceeded by a section | `_pack` truncates with binary trim; logs `WARNING chunk truncated`; chunk is included but shorter than original. |
| I-09 | Embedding model not in HuggingFace cache and no internet | `AutoTokenizer.from_pretrained` / `SentenceTransformer` raises; entire embed phase fails; index phase never runs. |
| I-10 | `data/chroma/` does not exist on first run | `Path(resolved_path).mkdir(parents=True, exist_ok=True)` in indexer creates it. |
| I-11 | Re-run with identical HTML (content unchanged) | `chunk_text_hash` unchanged; indexer skips all writes (`skipped_unchanged = N`); fast no-op. |
| I-12 | Re-run with one scheme's HTML changed | Only changed chunks upserted; unchanged chunks skipped; collection stays consistent. |
| I-13 | Two concurrent ingest runs with same `run_id` | Both write to same `data/raw/<run_id>/` directory; second run overwrites files; last writer wins. Chunk IDs are deterministic so upserts are idempotent. |
| I-14 | `min_success_ratio` = 1.0 and one URL fails | Scraper exits code 1; CI step fails; downstream phases do not run (GitHub Actions stops on non-zero exit). |
| I-15 | Zero sections produced by normalizer for a scheme | Chunker writes zero chunks; zero embeddings; scheme absent from index for that run; retrieval finds nothing for that scheme. |

---

## 7. Multi-Thread Chat (§8)

| ID | Scenario | Expected behaviour |
|----|----------|--------------------|
| T-01 | `POST /threads/{id}/messages` with unknown `thread_id` | `ThreadStore.get_thread` returns `None`; `ThreadedChat.post_user_message` raises `ValueError`; API returns HTTP 404. |
| T-02 | First message in a brand-new thread | No prior user lines; query expansion returns query unchanged; retrieval proceeds normally. |
| T-03 | Follow-up "What about the exit load?" after discussing Mid Cap Fund | Prior user line includes "Mid Cap"; expanded query resolves scheme correctly. |
| T-04 | Follow-up references assistant phrasing ("you said NAV is X") | Query expansion uses **user lines only**, never assistant lines; assistant echo not included in expanded query. |
| T-05 | Thread with 50+ messages (well beyond `THREAD_MAX_TURNS=6`) | `recent_window` fetches last 12 rows (`n * 2`); only last 6 turns used for expansion. |
| T-06 | Two simultaneous POSTs to the same thread | SQLite WAL handles concurrent writers; messages serialised; both answers persist. No cross-contamination between queries. |
| T-07 | `THREAD_MAX_TURNS=0` in env | `_max_turns()` rejects `n ≤ 0` and returns default (6). |
| T-08 | `session_key` filter on `GET /threads` with no matching threads | Returns empty list `[]`, HTTP 200. |

---

## 8. API Layer (§9)

| ID | Scenario | Expected behaviour |
|----|----------|--------------------|
| A-01 | `POST /threads/{id}/messages` with `content` = "" | Pydantic `min_length=1` rejects; HTTP 422 Unprocessable Entity. |
| A-02 | `POST /threads/{id}/messages` with `content` > 4000 chars | Pydantic `max_length=4000` rejects; HTTP 422. |
| A-03 | Malformed JSON body | FastAPI returns HTTP 422. |
| A-04 | `POST /admin/reindex` with no `X-Admin-Secret` header | `x_admin_secret = None`; `None != expected_secret`; HTTP 401. |
| A-05 | `POST /admin/reindex` with wrong secret | HTTP 401. |
| A-06 | `POST /admin/reindex` with `ADMIN_REINDEX_SECRET` not set in env | HTTP 503 (`ADMIN_REINDEX_SECRET not configured`). |
| A-07 | `POST /admin/reindex` with correct secret | HTTP 501 stub response with workflow hint. |
| A-08 | `RUNTIME_API_DEBUG=0` (default) | `debug` field is `null` in POST response; `retrieval_debug_id` hidden from GET messages. |
| A-09 | `RUNTIME_API_DEBUG=1` | `debug` block present with `latency_ms`, `route_reason`, `model`, etc. |
| A-10 | `GET /threads/{id}/messages` for non-existent thread | HTTP 404. |
| A-11 | `GET /health` while Chroma path is unreachable | HTTP 200 (health check is shallow — it does not ping Chroma). Retrieval will fail at query time. |
| A-12 | API starts before ingest has ever run (`data/chroma/` empty) | `Retriever._ensure_collection()` calls `client.get_collection(name)` which raises `chromadb.errors.InvalidCollectionException` (collection does not exist). Unhandled — returns HTTP 500. **Gap: should return a graceful error or auto-create collection.** |
| A-13 | Concurrent requests to POST /threads/{id}/messages | Each request creates its own pipeline objects (Retriever/Generator lazy-init are module-level singletons — potential race on first init). Should be validated under load. |

---

## 9. Structured Facts Store (§3.4)

| ID | Scenario | Expected behaviour |
|----|----------|--------------------|
| F-01 | "What is the minimum SIP for HDFC ELSS?" | Scheme resolved; key-metrics chunk contains `Minimum SIP` row; answer cites the value from the indexed chunk. |
| F-02 | "What is the NAV of HDFC Mid Cap Fund today?" | "Today" is unanswerable (no real-time data); answer cites latest indexed NAV + `Last updated from sources: <fetched_at>`; staleness acknowledged by footer. |
| F-03 | NAV field is null in structured facts but present in the key-metrics chunk text | Retriever returns the chunk; LLM extracts the value from text. Structured facts miss is not fatal. |
| F-04 | `data/structured/latest.json` is missing | Only affects potential direct-lookup path (not yet wired into retrieval); retrieval from Chroma proceeds normally. |
| F-05 | "What is the expense ratio for Direct and Regular plans?" | Only Direct plan is indexed (registry URLs are Direct Growth); Regular plan data absent; answer should reflect only what's in the index; no invented values. |

---

## 10. Boundary & Stress Cases

| ID | Scenario | Expected behaviour |
|----|----------|--------------------|
| B-01 | Query is exactly 512 BGE tokens after prefix | BGE truncates at tokenizer limit; retrieval quality may degrade at the boundary. |
| B-02 | Query contains SQL injection: `'; DROP TABLE threads; --` | Passed to SQLite only as a parameter in prepared statements; no injection possible. Router and retrieval see it as plain text. |
| B-03 | Query contains HTML: `<script>alert(1)</script>` | Router treats as plain text; if returned in assistant answer, `linkifyText` in the UI HTML-escapes it before rendering. |
| B-04 | Very rapid successive sends on the same thread (10 messages in 1 second) | Each request independent; SQLite WAL serialises writes; no message loss expected but latency increases. |
| B-05 | Chunk ID SHA-1 collision (two different inputs produce same 16-char hex prefix) | Probability ~1 in 10^19; effectively impossible for this corpus size. Upsert would overwrite the earlier chunk silently. |
| B-06 | `fetched_at` field missing from chunk metadata | `RetrievalHit.fetched_at = None`; `_date_only(None)` returns `None`; `footer_date` stays `None`; footer says `Last updated from sources: unknown`. |
| B-07 | Groww page returns HTTP 200 with a Cloudflare CAPTCHA challenge page (no real HTML) | `__NEXT_DATA__` absent; normalizer marks scheme `failed`; previous index data remains until next successful scrape. |
| B-08 | BGE model produces a zero vector for a query | Cosine similarity undefined; Chroma returns results anyway (Chroma handles zero vectors by returning arbitrary order). Response quality undefined. |

---

## 11. UI / Static Client

| ID | Scenario | Expected behaviour |
|----|----------|--------------------|
| U-01 | API not running when UI loads | `GET /threads` fails; status bar shows "threads: Failed to fetch"; no crash. |
| U-02 | Network drops mid-send | `composer.submit` catch block fires; status bar shows error; send button re-enabled. |
| U-03 | Assistant response contains `₹` and `%` | `linkifyText` HTML-escapes `<`, `>`, `&` only; currency symbols pass through unescaped and render correctly. |
| U-04 | Very long assistant response (> 1000 chars) | Rendered in `<li>` with CSS overflow; no truncation in the DOM. |
| U-05 | `localStorage.getItem("activeThreadId")` returns a stale deleted thread ID | `selectThread` calls `GET /threads/{id}/messages` → 404; status bar shows error; user must create a new thread. |
| U-06 | User opens UI in two browser tabs simultaneously | Both tabs share `localStorage`; switching thread in one tab does not update the other. Known limitation of the single-page static client. |

---

## 12. Regression Checklist (run after any change)

These are the minimum cases to verify after every code change:

1. **S-01** — advisory refusal fires before retrieval  
2. **P-01** — PAN in query refused and redacted in logs  
3. **R-01** — scheme resolved, key-metrics chunk retrieved  
4. **R-12** — empty collection → graceful fallback (not 500)  
5. **G-12** — missing GROQ_API_KEY → fallback, no crash  
6. **G-09** — double validation failure → fallback with scheme URL  
7. **I-11** — identical re-ingest is a no-op (skipped_unchanged = total chunks)  
8. **T-01** — unknown thread_id → HTTP 404  
9. **A-01** — empty content body → HTTP 422  
10. **A-12** — missing Chroma collection → handle gracefully (currently a gap)
