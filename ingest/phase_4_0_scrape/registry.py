from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable
from urllib.parse import urlparse

import yaml


@dataclass(frozen=True)
class RegistryEntry:
    scheme_id: str
    scheme_name: str
    url: str
    amc: str
    source_type: str
    category: str | None = None


def load_registry(path: str | Path) -> list[RegistryEntry]:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))

    amc = raw["amc"]
    default_type = raw.get("default_source_type", "groww_scheme_page")
    allowed_hosts = {h.lower() for h in raw.get("allowed_hosts", [])}

    entries: list[RegistryEntry] = []
    seen_ids: set[str] = set()
    for item in raw["urls"]:
        url = item["url"]
        host = urlparse(url).hostname or ""
        if allowed_hosts and host.lower() not in allowed_hosts:
            raise ValueError(
                f"URL host {host!r} not in allowed_hosts {sorted(allowed_hosts)}"
            )
        scheme_id = item["scheme_id"]
        if scheme_id in seen_ids:
            raise ValueError(f"Duplicate scheme_id in registry: {scheme_id}")
        seen_ids.add(scheme_id)

        entries.append(
            RegistryEntry(
                scheme_id=scheme_id,
                scheme_name=item["scheme_name"],
                url=url,
                amc=amc,
                source_type=item.get("source_type", default_type),
                category=item.get("category"),
            )
        )
    return entries


def slug_for(entry: RegistryEntry) -> str:
    return entry.scheme_id


def iter_urls(entries: Iterable[RegistryEntry]) -> list[str]:
    return [e.url for e in entries]
