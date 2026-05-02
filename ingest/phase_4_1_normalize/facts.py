from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


def _to_iso_date(s: str | None) -> str | None:
    if not s:
        return None
    for fmt in ("%d-%b-%Y", "%Y-%m-%d", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date().isoformat()
        except ValueError:
            continue
    return None


def _num(v: Any) -> float | int | None:
    if v is None:
        return None
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        s = v.strip().replace(",", "")
        if not s:
            return None
        try:
            f = float(s)
            return int(f) if f.is_integer() else f
        except ValueError:
            return None
    return None


@dataclass
class SchemeFacts:
    """Structured facts per Rag-Architecture.md §3.4.

    Fields: scheme identity + (nav, minimum_investment, minimum_sip,
    fund_size_aum, expense_ratio, rating). Missing values stay None;
    parse warnings are returned alongside.
    """

    scheme_id: str
    scheme_name: str
    amc: str
    source_url: str
    fetched_at: str
    raw_content_hash: str | None
    nav: dict[str, Any] | None
    minimum_investment: dict[str, Any] | None
    minimum_sip: dict[str, Any] | None
    fund_size_aum: dict[str, Any] | None
    expense_ratio: dict[str, Any] | None
    rating: dict[str, Any] | None
    warnings: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def extract_facts(
    *,
    scheme_id: str,
    scheme_name: str,
    amc: str,
    source_url: str,
    fetched_at: str,
    raw_content_hash: str | None,
    plan_type: str | None,
    server_data: dict[str, Any],
) -> SchemeFacts:
    """Build a SchemeFacts row from a Groww `mfServerSideData` blob."""
    warnings: list[str] = []

    def warn_if_none(value: Any, label: str) -> None:
        if value is None:
            warnings.append(f"missing:{label}")

    nav_value = _num(server_data.get("nav"))
    nav_date = _to_iso_date(server_data.get("nav_date"))
    nav = (
        {"value": nav_value, "currency": "INR", "as_of": nav_date}
        if nav_value is not None
        else None
    )
    warn_if_none(nav_value, "nav")

    min_inv = _num(server_data.get("min_investment_amount"))
    minimum_investment = (
        {"value": min_inv, "currency": "INR"} if min_inv is not None else None
    )
    warn_if_none(min_inv, "min_investment_amount")

    min_sip = _num(server_data.get("min_sip_investment"))
    minimum_sip = (
        {"value": min_sip, "currency": "INR"} if min_sip is not None else None
    )
    warn_if_none(min_sip, "min_sip_investment")

    aum = _num(server_data.get("aum"))
    fund_size_aum = (
        {"value": aum, "unit": "INR_CR", "currency": "INR"} if aum is not None else None
    )
    warn_if_none(aum, "aum")

    exp = _num(server_data.get("expense_ratio"))
    expense_ratio = (
        {"value": exp, "unit": "percent", "plan": plan_type}
        if exp is not None
        else None
    )
    warn_if_none(exp, "expense_ratio")

    groww_rating = _num(server_data.get("groww_rating"))
    crisil_raw = server_data.get("crisil_rating")
    crisil = _num(crisil_raw) if crisil_raw is not None else None
    # risk_category: "Very High Risk", "High Risk", "Moderately High Risk", etc.
    risk_category = (
        server_data.get("risk_category")
        or server_data.get("riskometer")
        or server_data.get("risk")
        or None
    )
    if isinstance(risk_category, str):
        risk_category = risk_category.strip() or None
    if groww_rating is None and crisil is None and risk_category is None:
        rating = None
        warnings.append("missing:rating")
    else:
        rating = {
            "groww": groww_rating,
            "crisil": crisil,
            "risk_category": risk_category,
            "kind": "riskometer" if risk_category is not None else (
                "groww" if groww_rating is not None else "crisil"
            ),
        }

    return SchemeFacts(
        scheme_id=scheme_id,
        scheme_name=scheme_name,
        amc=amc,
        source_url=source_url,
        fetched_at=fetched_at,
        raw_content_hash=raw_content_hash,
        nav=nav,
        minimum_investment=minimum_investment,
        minimum_sip=minimum_sip,
        fund_size_aum=fund_size_aum,
        expense_ratio=expense_ratio,
        rating=rating,
        warnings=warnings,
    )
