"""Phase 7 — Refusal & Safety Layer.

See docs/rag-architecture.md §7.

* §7.1 Advisory / comparative router: rule-based, runs BEFORE retrieval.
  Detects "should I", "which is better", "best fund", "recommend",
  implicit ranking, personal situation cues. Action on hit: skip phases
  5+6, return a templated refusal with one educational link
  (`EDUCATIONAL_URL`, default AMFI investor education).
* §7.2 Post-generation validation: implemented inside phase 6
  (`runtime.phase_6_generation.validate_answer`) — exit-load / sentence /
  URL-allowlist / forbidden-phrase checks with one retry + fallback.
  Phase 7 surfaces the same outcome through `answer()`.
* §7.3 Privacy: detect PII before sending to retrieval/LLM and refuse
  with a short non-judgmental message; redact PII tokens in any
  log line emitted by this module.

`answer()` is the public orchestration entrypoint: router → phase 5
retrieval → phase 6 generation, returning a uniform `SafeAnswer`.
"""
from __future__ import annotations

import logging
import os
import re
from dataclasses import asdict, dataclass, field
from typing import Any

from runtime.phase_5_retrieval import RetrievalResult, Retriever
from runtime.phase_6_generation import Generator, GenerationResult

log = logging.getLogger(__name__)


DEFAULT_EDUCATIONAL_URL = (
    "https://www.amfiindia.com/investor-corner/investor-center/learn-about-mfs.html"
)
FOOTER_PREFIX = "Last updated from sources:"


# ---------- §7.1 advisory router ----------

# Keep patterns conservative — false positives turn legitimate factual
# questions into refusals. Each pattern represents ONE failure mode the
# architecture explicitly calls out.
_ADVISORY_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("personal_advice", re.compile(r"\bshould\s+i\b", re.IGNORECASE)),
    ("recommendation", re.compile(r"\brecommend(?:ation|ed|s|ing)?\b", re.IGNORECASE)),
    ("ranking_best", re.compile(r"\bbest\s+(?:\w+\s+){0,3}(?:fund|scheme|mutual\s+fund|investment|amc)\b", re.IGNORECASE)),
    ("comparison_better", re.compile(r"\bwhich\s+(?:\w+\s+){0,3}(?:better|best)\b", re.IGNORECASE)),
    ("comparison_vs", re.compile(r"\b(?:vs\.?|versus)\b", re.IGNORECASE)),
    ("opinion", re.compile(r"\b(?:do\s+you\s+think|in\s+your\s+opinion|your\s+opinion)\b", re.IGNORECASE)),
    ("personal_situation", re.compile(
        r"\bi\s+am\s+\d{1,2}\b|"           # "I am 45"
        r"\bmy\s+(?:age|salary|income|portfolio|risk)\b|"
        r"\bfor\s+my\s+(?:retirement|child|kids?|family)\b",
        re.IGNORECASE,
    )),
    ("future_promise", re.compile(
        r"\b(?:will\s+(?:give|return|grow|beat)|guaranteed?\s+returns?|"
        r"how\s+much\s+will\s+i\s+(?:earn|make|get))\b",
        re.IGNORECASE,
    )),
]


# ---------- §7.3 PII heuristics ----------

_PII_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    # PAN: 5 letters + 4 digits + 1 letter.
    ("pan", re.compile(r"\b[A-Z]{5}[0-9]{4}[A-Z]\b")),
    # Aadhaar: 12 digits, optionally space-grouped 4-4-4.
    ("aadhaar", re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b")),
    # Email.
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b")),
    # Indian phone: optional +91/0, then 10 digits starting 6-9.
    ("phone", re.compile(r"(?:(?:\+91[\s-]?)|\b0)?[6-9]\d{9}\b")),
    # 6-digit OTP-ish in context.
    ("otp", re.compile(r"\botp\s*[:=]?\s*\d{4,8}\b", re.IGNORECASE)),
]


# ---------- result types ----------


@dataclass
class RouteDecision:
    """Result of the §7.1 router.

    `allow=True` means the query is in-scope; phases 5+6 will run.
    `allow=False` means refuse with `template_response`.
    """

    allow: bool
    reason: str  # "ok" | advisory category | "pii_<kind>"
    matched_pattern: str | None = None
    template_response: str | None = None


@dataclass
class SafeAnswer:
    """Uniform output of the safety-orchestrated pipeline."""

    answer: str
    citation_url: str | None
    footer_date: str | None
    route_reason: str
    refused: bool
    used_fallback: bool
    retried: bool
    validation_errors: list[str] = field(default_factory=list)
    model: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ---------- helpers ----------


def _today_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def educational_url() -> str:
    return os.getenv("EDUCATIONAL_URL", DEFAULT_EDUCATIONAL_URL)


def _refusal_advisory(reason: str) -> str:
    url = educational_url()
    date = _today_iso()
    return (
        "I cannot provide investment advice or compare schemes. "
        "For general investor education, see the linked resource. "
        f"{url}\n"
        f"{FOOTER_PREFIX} {date}"
    )


def _refusal_pii(kind: str) -> str:
    url = educational_url()
    date = _today_iso()
    return (
        "I cannot accept personal identifiers (PAN, Aadhaar, account numbers, "
        "email, phone, OTP). Please re-ask without sharing any personal data. "
        f"{url}\n"
        f"{FOOTER_PREFIX} {date}"
    )


def detect_pii(text: str) -> tuple[str | None, str | None]:
    """Return (kind, matched-substring-redacted) or (None, None)."""
    for kind, pat in _PII_PATTERNS:
        m = pat.search(text)
        if m:
            return kind, "***"
    return None, None


def redact_pii(text: str) -> str:
    """Return text with PII spans replaced by `[REDACTED:<kind>]`."""
    out = text
    for kind, pat in _PII_PATTERNS:
        out = pat.sub(f"[REDACTED:{kind}]", out)
    return out


# ---------- §7.1 router ----------


def route(query: str) -> RouteDecision:
    """Classify a query before retrieval. PII first, then advisory rules."""
    if not query or not query.strip():
        return RouteDecision(
            allow=False,
            reason="empty",
            template_response=_refusal_advisory("empty"),
        )

    # §7.3 PII check happens BEFORE anything is logged or sent downstream.
    kind, _ = detect_pii(query)
    if kind:
        # Note: redact in any log line we emit.
        log.info("phase 7 router: refusing for pii kind=%s query=%r", kind, redact_pii(query))
        return RouteDecision(
            allow=False,
            reason=f"pii_{kind}",
            matched_pattern=kind,
            template_response=_refusal_pii(kind),
        )

    # §7.1 advisory rules.
    for name, pat in _ADVISORY_PATTERNS:
        if pat.search(query):
            log.info("phase 7 router: refusing advisory match=%s", name)
            return RouteDecision(
                allow=False,
                reason=name,
                matched_pattern=pat.pattern,
                template_response=_refusal_advisory(name),
            )

    return RouteDecision(allow=True, reason="ok")


# ---------- public orchestration ----------


class SafetyPipeline:
    def __init__(
        self,
        *,
        retriever: Retriever | None = None,
        generator: Generator | None = None,
    ) -> None:
        self._retriever = retriever
        self._generator = generator

    def _ensure_retriever(self) -> Retriever:
        if self._retriever is None:
            self._retriever = Retriever()
        return self._retriever

    def _ensure_generator(self) -> Generator:
        if self._generator is None:
            self._generator = Generator(retriever=self._ensure_retriever())
        return self._generator

    def answer(self, query: str) -> SafeAnswer:
        decision = route(query)
        if not decision.allow:
            return SafeAnswer(
                answer=decision.template_response or "",
                citation_url=educational_url(),
                footer_date=_today_iso(),
                route_reason=decision.reason,
                refused=True,
                used_fallback=False,
                retried=False,
                validation_errors=[],
                model="",
            )

        retrieval: RetrievalResult = self._ensure_retriever().retrieve(query)
        gen: GenerationResult = self._ensure_generator().generate(
            query, retrieval=retrieval
        )
        return SafeAnswer(
            answer=gen.answer,
            citation_url=gen.citation_url,
            footer_date=gen.footer_date,
            route_reason=decision.reason,
            refused=False,
            used_fallback=gen.used_fallback,
            retried=gen.retried,
            validation_errors=list(gen.validation_errors),
            model=gen.model,
        )


_default_pipeline: SafetyPipeline | None = None


def answer(query: str) -> SafeAnswer:
    global _default_pipeline
    if _default_pipeline is None:
        _default_pipeline = SafetyPipeline()
    return _default_pipeline.answer(query)
