from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from .facts import SchemeFacts, extract_facts

log = logging.getLogger(__name__)


SOURCE_TYPE = "groww_scheme_page"


@dataclass
class NormalizeResult:
    scheme_id: str
    scheme_name: str
    source_url: str
    status: str  # "ok" | "failed"
    normalized_path: str | None
    section_count: int
    facts_warnings: list[str] = field(default_factory=list)
    error: str | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_next_data(html: str) -> dict[str, Any]:
    soup = BeautifulSoup(html, "lxml")
    tag = soup.find("script", id="__NEXT_DATA__")
    if tag is None or not tag.string:
        raise ValueError("__NEXT_DATA__ script not found")
    return json.loads(tag.string)


def _server_data(next_data: dict[str, Any]) -> dict[str, Any]:
    try:
        return next_data["props"]["pageProps"]["mfServerSideData"]
    except (KeyError, TypeError) as exc:
        raise ValueError("mfServerSideData missing in __NEXT_DATA__") from exc


def _fmt_inr(n: float | int | None) -> str:
    if n is None:
        return "—"
    if isinstance(n, float) and not n.is_integer():
        return f"₹{n:,.4f}".rstrip("0").rstrip(".")
    return f"₹{int(n):,}"


def _fmt_pct(n: float | int | None) -> str:
    return "—" if n is None else f"{n}%"


def _build_overview(ssd: dict[str, Any]) -> dict[str, Any] | None:
    description = (ssd.get("description") or "").strip()
    category = ssd.get("category")
    sub_category = ssd.get("sub_category")
    benchmark = ssd.get("benchmark_name")
    fund_manager = ssd.get("fund_manager")
    launch_date = ssd.get("launch_date")
    plan_type = ssd.get("plan_type")

    parts: list[str] = []
    if description:
        parts.append(description)

    bullets: list[str] = []
    if category or sub_category:
        bullets.append(
            f"Category: {category or '—'}"
            + (f" / {sub_category}" if sub_category else "")
        )
    if benchmark:
        bullets.append(f"Benchmark: {benchmark}")
    if fund_manager:
        bullets.append(f"Fund manager: {fund_manager}")
    if launch_date:
        bullets.append(f"Launch date: {launch_date}")
    if plan_type:
        bullets.append(f"Plan: {plan_type}")
    if bullets:
        parts.append("\n".join(f"- {b}" for b in bullets))

    if not parts:
        return None
    return {
        "section_id": "overview",
        "section_title": "Fund Overview",
        "kind": "prose",
        "text": "\n\n".join(parts),
    }


def _build_key_metrics(ssd: dict[str, Any], facts: SchemeFacts) -> dict[str, Any]:
    nav_val = facts.nav["value"] if facts.nav else None
    nav_date = facts.nav.get("as_of") if facts.nav else None
    aum_val = facts.fund_size_aum["value"] if facts.fund_size_aum else None
    exp_val = facts.expense_ratio["value"] if facts.expense_ratio else None
    min_inv_val = (
        facts.minimum_investment["value"] if facts.minimum_investment else None
    )
    min_sip_val = facts.minimum_sip["value"] if facts.minimum_sip else None

    rows: list[tuple[str, str]] = [
        (
            "NAV",
            _fmt_inr(nav_val) + (f" (as of {nav_date})" if nav_val is not None and nav_date else ""),
        ),
        ("Fund Size (AUM)", "—" if aum_val is None else f"₹{aum_val:,.2f} Cr"),
        (
            "Expense Ratio",
            _fmt_pct(exp_val)
            + (f" ({facts.expense_ratio['plan']})" if exp_val is not None and facts.expense_ratio and facts.expense_ratio.get("plan") else ""),
        ),
        ("Minimum Investment", _fmt_inr(min_inv_val)),
        ("Minimum SIP", _fmt_inr(min_sip_val)),
    ]
    if facts.rating:
        groww = facts.rating.get("groww")
        crisil = facts.rating.get("crisil")
        rating_parts = []
        if groww is not None:
            rating_parts.append(f"Groww: {groww}/5")
        if crisil is not None:
            rating_parts.append(f"CRISIL: {crisil}")
        if rating_parts:
            rows.append(("Rating", " · ".join(rating_parts)))

    md = "| Metric | Value |\n| --- | --- |\n" + "\n".join(
        f"| {label} | {value} |" for label, value in rows
    )
    return {
        "section_id": "key-metrics",
        "section_title": "Key Metrics",
        "kind": "table",
        "text": md,
    }


def _build_exit_load(ssd: dict[str, Any]) -> dict[str, Any] | None:
    text = (ssd.get("exit_load") or "").strip()
    if not text:
        return None
    return {
        "section_id": "exit-load",
        "section_title": "Exit Load",
        "kind": "prose",
        "text": text,
    }


def _build_analysis(ssd: dict[str, Any]) -> list[dict[str, Any]]:
    items = ssd.get("analysis") or []
    pros: list[str] = []
    cons: list[str] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        kind = (item.get("analysis_type") or "").upper()
        desc = (item.get("analysis_desc") or "").strip()
        if not desc:
            continue
        if kind == "PROS":
            pros.append(desc)
        elif kind == "CONS":
            cons.append(desc)

    out: list[dict[str, Any]] = []
    if pros:
        out.append(
            {
                "section_id": "analysis-pros",
                "section_title": "Analysis: Pros",
                "kind": "list",
                "text": "\n".join(f"- {p}" for p in pros),
            }
        )
    if cons:
        out.append(
            {
                "section_id": "analysis-cons",
                "section_title": "Analysis: Cons",
                "kind": "list",
                "text": "\n".join(f"- {c}" for c in cons),
            }
        )
    return out


def normalize_one(
    *,
    html: str,
    scheme_id: str,
    scheme_name: str,
    amc: str,
    source_url: str,
    fetched_at: str,
    raw_content_hash: str | None,
) -> tuple[dict[str, Any], SchemeFacts]:
    next_data = _load_next_data(html)
    ssd = _server_data(next_data)

    facts = extract_facts(
        scheme_id=scheme_id,
        scheme_name=scheme_name,
        amc=amc,
        source_url=source_url,
        fetched_at=fetched_at,
        raw_content_hash=raw_content_hash,
        plan_type=ssd.get("plan_type"),
        server_data=ssd,
    )

    sections: list[dict[str, Any]] = []
    overview = _build_overview(ssd)
    if overview is not None:
        sections.append(overview)
    sections.append(_build_key_metrics(ssd, facts))
    exit_load = _build_exit_load(ssd)
    if exit_load is not None:
        sections.append(exit_load)
    sections.extend(_build_analysis(ssd))

    normalized = {
        "scheme_id": scheme_id,
        "scheme_name": scheme_name,
        "amc": amc,
        "source_url": source_url,
        "source_type": SOURCE_TYPE,
        "fetched_at": fetched_at,
        "raw_content_hash": raw_content_hash,
        "sections": sections,
    }
    return normalized, facts


def _read_scrape_manifest(raw_run_dir: Path) -> dict[str, dict[str, Any]]:
    manifest_path = raw_run_dir / "manifest.json"
    if not manifest_path.exists():
        return {}
    data = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_id: dict[str, dict[str, Any]] = {}
    for r in data.get("results", []):
        by_id[r["scheme_id"]] = r
    return by_id


def normalize_all(
    raw_run_dir: Path,
    normalized_root: Path,
    structured_root: Path,
    *,
    amc: str,
    scheme_name_overrides: dict[str, str] | None = None,
) -> tuple[Path, Path, list[NormalizeResult], list[SchemeFacts]]:
    """Normalize every successful HTML in raw_run_dir.

    Returns (normalized_run_dir, structured_run_dir, results, facts_list).
    """
    run_id = raw_run_dir.name
    normalized_run_dir = Path(normalized_root) / run_id
    structured_run_dir = Path(structured_root) / run_id
    normalized_run_dir.mkdir(parents=True, exist_ok=True)
    structured_run_dir.mkdir(parents=True, exist_ok=True)

    scrape_by_id = _read_scrape_manifest(raw_run_dir)
    overrides = scheme_name_overrides or {}

    results: list[NormalizeResult] = []
    facts_list: list[SchemeFacts] = []

    for html_path in sorted(raw_run_dir.glob("*.html")):
        scheme_id = html_path.stem
        scrape = scrape_by_id.get(scheme_id, {})
        if scrape and scrape.get("status") != "ok":
            continue
        source_url = scrape.get("url") or ""
        fetched_at = scrape.get("fetched_at") or _now_iso()
        raw_content_hash = scrape.get("content_hash")
        scheme_name = (
            overrides.get(scheme_id)
            or scrape.get("scheme_name")
            or scheme_id
        )

        try:
            html = html_path.read_text(encoding="utf-8")
            normalized, facts = normalize_one(
                html=html,
                scheme_id=scheme_id,
                scheme_name=scheme_name,
                amc=amc,
                source_url=source_url,
                fetched_at=fetched_at,
                raw_content_hash=raw_content_hash,
            )
        except Exception as exc:  # noqa: BLE001
            log.warning("normalize failed for %s: %s", scheme_id, exc)
            results.append(
                NormalizeResult(
                    scheme_id=scheme_id,
                    scheme_name=scheme_name,
                    source_url=source_url,
                    status="failed",
                    normalized_path=None,
                    section_count=0,
                    error=str(exc),
                )
            )
            continue

        out_path = normalized_run_dir / f"{scheme_id}.json"
        out_path.write_text(
            json.dumps(normalized, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        facts_list.append(facts)
        results.append(
            NormalizeResult(
                scheme_id=scheme_id,
                scheme_name=scheme_name,
                source_url=source_url,
                status="ok",
                normalized_path=str(out_path.relative_to(normalized_run_dir.parent)),
                section_count=len(normalized["sections"]),
                facts_warnings=facts.warnings,
            )
        )

    facts_path = structured_run_dir / "scheme_facts.json"
    facts_path.write_text(
        json.dumps([f.to_dict() for f in facts_list], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    latest_path = Path(structured_root) / "latest.json"
    latest_path.write_text(
        json.dumps([f.to_dict() for f in facts_list], indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    manifest = {
        "run_id": run_id,
        "phase": "4.1_normalize",
        "amc": amc,
        "finished_at": _now_iso(),
        "total": len(results),
        "ok": sum(1 for r in results if r.status == "ok"),
        "failed": sum(1 for r in results if r.status == "failed"),
        "facts_path": str(facts_path.relative_to(structured_run_dir.parent)),
        "results": [asdict(r) for r in results],
    }
    (normalized_run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return normalized_run_dir, structured_run_dir, results, facts_list
