"""Phase 6 — Generation Layer (Groq).

See docs/rag-architecture.md §6.

* §6.1 Prompting: facts-only, no recommendations, no comparisons,
  <=3 sentences, exactly one URL from CONTEXT metadata, required footer.
* §6.2 Output schema: body (<=3 sentences) + citation URL + footer
  "Last updated from sources: <date>".
* §6.3 Model choice: Groq `llama-3.1-8b-instant` (env `GROQ_MODEL`),
  low temperature for determinism.
* §7.2 Post-validation runs here too: sentence count, exactly one URL on
  allowlist, forbidden phrases. One retry with stricter prompt, then a
  templated safe fallback citing the resolved scheme URL.

Footer policy: date of the cited source only (cited chunk's `fetched_at`,
truncated to YYYY-MM-DD). Documented here so future ops know.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from runtime.phase_5_retrieval import RetrievalResult, Retriever

log = logging.getLogger(__name__)


GROQ_API_URL = "https://api.groq.com/openai/v1/chat/completions"
DEFAULT_MODEL = "llama-3.1-8b-instant"
DEFAULT_TEMPERATURE = 0.1
DEFAULT_MAX_TOKENS = 350
HTTP_TIMEOUT = 30.0
FOOTER_PREFIX = "Last updated from sources:"

SYSTEM_PROMPT = (
    "You are a facts-only mutual-fund FAQ assistant for HDFC schemes.\n"
    "Hard rules:\n"
    "1. Use ONLY the CONTEXT below. If the CONTEXT does not contain the answer, "
    "say you cannot find it in the indexed sources and point to the relevant "
    "scheme URL from CONTEXT metadata.\n"
    "2. Reply in AT MOST 3 sentences. No bullet lists. No headings.\n"
    "3. Include EXACTLY ONE URL, and it must be the `Source URL:` value from "
    "the CONTEXT block you used. Do not invent or shorten URLs.\n"
    "4. End with a final line exactly of the form: "
    "`Last updated from sources: <YYYY-MM-DD>` using the date provided.\n"
    "5. Do NOT give recommendations, opinions, comparisons, predictions, or "
    "any phrasing like 'you should', 'better than', 'invest in', 'outperform', "
    "'guarantee'. State facts only.\n"
)

STRICTER_RETRY_SUFFIX = (
    "\nThe previous draft violated the rules. Re-emit a corrected answer that "
    "satisfies every rule, especially: <=3 sentences, exactly one URL "
    "(the Source URL from CONTEXT), and the required footer line."
)

# §7.2 forbidden phrases. Keep narrow — these match the architecture doc.
_FORBIDDEN_PATTERNS = [
    re.compile(r"\byou\s+should\b", re.IGNORECASE),
    re.compile(r"\binvest\s+in\b", re.IGNORECASE),
    re.compile(r"\bbetter\s+than\b", re.IGNORECASE),
    re.compile(r"\boutperform(?:ed|ing|s)?\b", re.IGNORECASE),
    re.compile(r"\bguarantee[sd]?\b", re.IGNORECASE),
    re.compile(r"\brecommend(?:ed|ing|s)?\b", re.IGNORECASE),
]

_URL_PATTERN = re.compile(r"https?://[^\s<>)\]]+", re.IGNORECASE)
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")


@dataclass
class GenerationResult:
    answer: str
    citation_url: str | None
    footer_date: str | None
    used_fallback: bool
    retried: bool
    validation_errors: list[str] = field(default_factory=list)
    model: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------- §6.1 context packaging ----------


def _date_only(ts: str | None) -> str | None:
    if not ts:
        return None
    # Accept "2026-04-26", "2026-04-26T14:24:26Z", etc.
    return ts[:10] if len(ts) >= 10 else None


def _normalize_url(u: str) -> str:
    """Drop fragment and trailing slash for allowlist comparison."""
    if not u:
        return ""
    parts = urlsplit(u)
    path = parts.path.rstrip("/")
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, parts.query, ""))


def _load_allowlist(registry_path: str | Path) -> set[str]:
    import yaml  # type: ignore

    p = Path(registry_path)
    if not p.exists():
        return set()
    raw = yaml.safe_load(p.read_text(encoding="utf-8"))
    return {_normalize_url(item["url"]) for item in raw.get("urls", [])}


def pack_context(result: RetrievalResult, *, max_chunks: int = 5) -> tuple[str, str | None]:
    """Return (CONTEXT block, footer_date). Footer date = cited chunk's fetched_at."""
    if not result.hits or not result.citation_url:
        return "", None

    cited_norm = _normalize_url(result.citation_url)
    cited_hits = [h for h in result.hits if _normalize_url(h.source_url) == cited_norm]
    if not cited_hits:
        cited_hits = result.hits[:max_chunks]

    footer_date = None
    blocks: list[str] = []
    for i, h in enumerate(cited_hits[:max_chunks]):
        d = _date_only(h.fetched_at)
        if d and (footer_date is None or d > footer_date):
            footer_date = d
        title = h.section_title or h.section_id or "section"
        blocks.append(
            f"[CHUNK {i+1}]\n"
            f"Source URL: {h.source_url}\n"
            f"Section: {title}\n"
            f"Scheme: {h.scheme_name or h.scheme_id or 'n/a'}\n"
            f"Text:\n{h.text.strip()}"
        )
    return "\n\n".join(blocks), footer_date


def _build_user_message(query: str, context: str, footer_date: str | None) -> str:
    date_str = footer_date or "unknown"
    return (
        f"CONTEXT:\n{context}\n\n"
        f"QUESTION: {query}\n\n"
        f"Use the date `{date_str}` in the required footer line."
    )


# ---------- §7.2 validation ----------


def _count_sentences(text: str) -> int:
    body = text.strip()
    # Strip footer line so it doesn't add an extra sentence.
    body = re.sub(rf"(?im)^{re.escape(FOOTER_PREFIX)}.*$", "", body).strip()
    if not body:
        return 0
    parts = _SENTENCE_SPLIT.split(body)
    return sum(1 for p in parts if p.strip())


def validate_answer(
    text: str,
    *,
    expected_url: str | None,
    allowlist: set[str],
    expected_footer_date: str | None,
) -> list[str]:
    errors: list[str] = []
    body = text.strip()

    sentences = _count_sentences(body)
    if sentences == 0:
        errors.append("empty answer")
    elif sentences > 3:
        errors.append(f"too many sentences ({sentences})")

    urls = _URL_PATTERN.findall(body)
    if len(urls) == 0:
        errors.append("no URL")
    elif len(urls) > 1:
        errors.append(f"multiple URLs ({len(urls)})")
    else:
        norm = _normalize_url(urls[0].rstrip(".,);"))
        if allowlist and norm not in allowlist:
            errors.append("URL not on allowlist")
        if expected_url and norm != _normalize_url(expected_url):
            errors.append("URL does not match retrieved citation")

    for pat in _FORBIDDEN_PATTERNS:
        if pat.search(body):
            errors.append(f"forbidden phrase: {pat.pattern}")
            break

    footer_re = re.compile(
        rf"(?im)^{re.escape(FOOTER_PREFIX)}\s*(\d{{4}}-\d{{2}}-\d{{2}})\s*$"
    )
    m = footer_re.search(body)
    if not m:
        errors.append("missing or malformed footer")
    elif expected_footer_date and m.group(1) != expected_footer_date:
        errors.append("footer date does not match cited source")

    return errors


# ---------- Groq client ----------


def _call_groq(
    messages: list[dict[str, str]],
    *,
    model: str,
    api_key: str,
    temperature: float = DEFAULT_TEMPERATURE,
    max_tokens: int = DEFAULT_MAX_TOKENS,
) -> str:
    import httpx  # already in requirements

    payload = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    r = httpx.post(GROQ_API_URL, json=payload, headers=headers, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    data = r.json()
    return data["choices"][0]["message"]["content"]


# ---------- fallback ----------


def _templated_fallback(
    citation_url: str | None, footer_date: str | None
) -> str:
    url = citation_url or "https://www.amfiindia.com/"
    date = footer_date or "unknown"
    return (
        "I cannot find this in the indexed sources. "
        f"Please refer to the scheme page: {url}\n"
        f"{FOOTER_PREFIX} {date}"
    )


# ---------- public entrypoint ----------


class Generator:
    def __init__(
        self,
        *,
        retriever: Retriever | None = None,
        model: str | None = None,
        api_key: str | None = None,
        registry_path: str | None = None,
    ) -> None:
        self.retriever = retriever
        self.model = model or os.getenv("GROQ_MODEL", DEFAULT_MODEL)
        self._api_key = api_key or os.getenv("GROQ_API_KEY", "")
        self.registry_path = registry_path or os.getenv(
            "INGEST_REGISTRY_PATH", "data/registry/urls.yaml"
        )
        self._allowlist: set[str] | None = None

    def _ensure_retriever(self) -> Retriever:
        if self.retriever is None:
            self.retriever = Retriever()
        return self.retriever

    def _ensure_allowlist(self) -> set[str]:
        if self._allowlist is None:
            self._allowlist = _load_allowlist(self.registry_path)
        return self._allowlist

    def generate(
        self,
        query: str,
        *,
        retrieval: RetrievalResult | None = None,
    ) -> GenerationResult:
        if retrieval is None:
            retrieval = self._ensure_retriever().retrieve(query)

        context, footer_date = pack_context(retrieval)

        # No context found → safe fallback.
        if not context or not retrieval.citation_url:
            return GenerationResult(
                answer=_templated_fallback(retrieval.citation_url, footer_date),
                citation_url=retrieval.citation_url,
                footer_date=footer_date,
                used_fallback=True,
                retried=False,
                validation_errors=["no context retrieved"],
                model=self.model,
            )

        if not self._api_key:
            log.warning("GROQ_API_KEY not set — emitting templated fallback")
            return GenerationResult(
                answer=_templated_fallback(retrieval.citation_url, footer_date),
                citation_url=retrieval.citation_url,
                footer_date=footer_date,
                used_fallback=True,
                retried=False,
                validation_errors=["GROQ_API_KEY missing"],
                model=self.model,
            )

        allowlist = self._ensure_allowlist()
        user_msg = _build_user_message(query, context, footer_date)
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_msg},
        ]

        # First attempt.
        answer = _call_groq(messages, model=self.model, api_key=self._api_key)
        errors = validate_answer(
            answer,
            expected_url=retrieval.citation_url,
            allowlist=allowlist,
            expected_footer_date=footer_date,
        )
        retried = False

        if errors:
            log.info("phase 6 first-pass failed validation: %s", errors)
            retried = True
            messages_strict = [
                {"role": "system", "content": SYSTEM_PROMPT + STRICTER_RETRY_SUFFIX},
                {"role": "user", "content": user_msg},
                {"role": "assistant", "content": answer},
                {
                    "role": "user",
                    "content": (
                        "Validation errors: "
                        + "; ".join(errors)
                        + ". Emit a corrected answer following every rule."
                    ),
                },
            ]
            answer = _call_groq(
                messages_strict,
                model=self.model,
                api_key=self._api_key,
                temperature=0.0,
            )
            errors = validate_answer(
                answer,
                expected_url=retrieval.citation_url,
                allowlist=allowlist,
                expected_footer_date=footer_date,
            )

        if errors:
            log.warning("phase 6 retry still invalid (%s) — using fallback", errors)
            return GenerationResult(
                answer=_templated_fallback(retrieval.citation_url, footer_date),
                citation_url=retrieval.citation_url,
                footer_date=footer_date,
                used_fallback=True,
                retried=retried,
                validation_errors=errors,
                model=self.model,
            )

        return GenerationResult(
            answer=answer.strip(),
            citation_url=retrieval.citation_url,
            footer_date=footer_date,
            used_fallback=False,
            retried=retried,
            validation_errors=[],
            model=self.model,
        )


_default_generator: Generator | None = None


def generate(query: str) -> GenerationResult:
    global _default_generator
    if _default_generator is None:
        _default_generator = Generator()
    return _default_generator.generate(query)
