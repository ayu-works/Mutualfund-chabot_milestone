from __future__ import annotations

import hashlib
import json
import logging
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable
from urllib import robotparser
from urllib.parse import urlparse

import httpx

from .registry import RegistryEntry, slug_for

log = logging.getLogger(__name__)

DEFAULT_USER_AGENT = (
    "mf-faq-assistant-ingest/0.1 (+https://github.com/your-org/mf-faq-assistant; "
    "contact: ops@example.com)"
)
DEFAULT_TIMEOUT_SECONDS = 30.0
DEFAULT_RATE_LIMIT_SECONDS = 1.5
DEFAULT_RETRIES = 2


@dataclass
class ScrapeResult:
    scheme_id: str
    scheme_name: str
    url: str
    status: str  # "ok" | "failed"
    http_status: int | None
    fetched_at: str
    content_hash: str | None
    bytes_written: int
    output_path: str | None
    error: str | None


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def make_run_id() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")


def _content_hash(body: bytes) -> str:
    return "sha256:" + hashlib.sha256(body).hexdigest()


def _build_robot_cache(
    urls: Iterable[str], user_agent: str, timeout: float
) -> dict[str, robotparser.RobotFileParser]:
    cache: dict[str, robotparser.RobotFileParser] = {}
    for url in urls:
        parts = urlparse(url)
        host_key = f"{parts.scheme}://{parts.netloc}"
        if host_key in cache:
            continue
        rp = robotparser.RobotFileParser()
        robots_url = f"{host_key}/robots.txt"
        try:
            with httpx.Client(timeout=timeout, headers={"User-Agent": user_agent}) as c:
                resp = c.get(robots_url)
            if resp.status_code == 200:
                rp.parse(resp.text.splitlines())
            else:
                # No robots.txt or unreadable -> default allow
                rp.parse([])
        except httpx.HTTPError as exc:
            log.warning("robots.txt fetch failed for %s: %s; defaulting to allow", host_key, exc)
            rp.parse([])
        cache[host_key] = rp
    return cache


def _fetch_one(
    client: httpx.Client,
    entry: RegistryEntry,
    out_dir: Path,
    retries: int,
) -> ScrapeResult:
    fetched_at = _now_iso()
    last_exc: Exception | None = None
    for attempt in range(retries + 1):
        try:
            resp = client.get(entry.url)
            if resp.status_code != 200:
                last_exc = httpx.HTTPStatusError(
                    f"HTTP {resp.status_code}", request=resp.request, response=resp
                )
            elif not resp.content:
                last_exc = ValueError("empty body")
            else:
                body = resp.content
                slug = slug_for(entry)
                path = out_dir / f"{slug}.html"
                path.write_bytes(body)
                return ScrapeResult(
                    scheme_id=entry.scheme_id,
                    scheme_name=entry.scheme_name,
                    url=entry.url,
                    status="ok",
                    http_status=resp.status_code,
                    fetched_at=fetched_at,
                    content_hash=_content_hash(body),
                    bytes_written=len(body),
                    output_path=str(path.relative_to(out_dir.parent)),
                    error=None,
                )
        except httpx.HTTPError as exc:
            last_exc = exc
        if attempt < retries:
            sleep_s = 2 ** attempt
            log.warning(
                "fetch failed for %s (attempt %d): %s; retrying in %ss",
                entry.url, attempt + 1, last_exc, sleep_s,
            )
            time.sleep(sleep_s)

    return ScrapeResult(
        scheme_id=entry.scheme_id,
        scheme_name=entry.scheme_name,
        url=entry.url,
        status="failed",
        http_status=getattr(getattr(last_exc, "response", None), "status_code", None),
        fetched_at=fetched_at,
        content_hash=None,
        bytes_written=0,
        output_path=None,
        error=str(last_exc) if last_exc else "unknown error",
    )


def scrape_all(
    entries: list[RegistryEntry],
    raw_root: Path,
    *,
    run_id: str | None = None,
    user_agent: str = DEFAULT_USER_AGENT,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    rate_limit_seconds: float = DEFAULT_RATE_LIMIT_SECONDS,
    retries: int = DEFAULT_RETRIES,
) -> tuple[Path, list[ScrapeResult]]:
    """Fetch every entry's URL into <raw_root>/<run_id>/, write manifest.json.

    Returns (run_dir, results). Results have status ok/failed; failures do not abort.
    """
    run_id = run_id or make_run_id()
    run_dir = Path(raw_root) / run_id
    run_dir.mkdir(parents=True, exist_ok=True)

    robot_cache = _build_robot_cache((e.url for e in entries), user_agent, timeout)

    results: list[ScrapeResult] = []
    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml",
        "Accept-Language": "en-IN,en;q=0.9",
    }

    with httpx.Client(timeout=timeout, headers=headers, follow_redirects=True) as client:
        for i, entry in enumerate(entries):
            parts = urlparse(entry.url)
            host_key = f"{parts.scheme}://{parts.netloc}"
            rp = robot_cache.get(host_key)
            if rp is not None and not rp.can_fetch(user_agent, entry.url):
                log.warning("robots.txt disallows %s for UA %s", entry.url, user_agent)
                results.append(
                    ScrapeResult(
                        scheme_id=entry.scheme_id,
                        scheme_name=entry.scheme_name,
                        url=entry.url,
                        status="failed",
                        http_status=None,
                        fetched_at=_now_iso(),
                        content_hash=None,
                        bytes_written=0,
                        output_path=None,
                        error="blocked by robots.txt",
                    )
                )
                continue

            if i > 0 and rate_limit_seconds > 0:
                time.sleep(rate_limit_seconds)

            log.info("fetching %s", entry.url)
            results.append(_fetch_one(client, entry, run_dir, retries))

    manifest = {
        "run_id": run_id,
        "phase": "4.0_scrape",
        "user_agent": user_agent,
        "started_at": results[0].fetched_at if results else _now_iso(),
        "finished_at": _now_iso(),
        "total": len(results),
        "ok": sum(1 for r in results if r.status == "ok"),
        "failed": sum(1 for r in results if r.status == "failed"),
        "results": [asdict(r) for r in results],
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return run_dir, results
