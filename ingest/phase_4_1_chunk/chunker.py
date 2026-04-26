from __future__ import annotations

import hashlib
import json
import logging
import re
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

log = logging.getLogger(__name__)


DEFAULT_MODEL_ID = "BAAI/bge-small-en-v1.5"
DEFAULT_TARGET_TOKENS = 400
DEFAULT_MAX_TOKENS = 488
DEFAULT_OVERLAP_TOKENS = 48


@dataclass
class ChunkRecord:
    chunk_id: str
    chunk_text: str
    chunk_text_hash: str
    token_count: int
    metadata: dict[str, Any]


@dataclass
class SchemeChunkResult:
    scheme_id: str
    status: str  # "ok" | "failed"
    chunk_count: int
    error: str | None = None


@dataclass
class ChunkRunStats:
    run_id: str
    total_schemes: int
    ok_schemes: int
    failed_schemes: int
    total_chunks: int
    truncated_chunks: int
    results: list[SchemeChunkResult] = field(default_factory=list)


TokenCounter = Callable[[str], int]


def make_token_counter(model_id: str = DEFAULT_MODEL_ID) -> tuple[TokenCounter, Any]:
    """Return (count_fn, tokenizer). Counts via the model's own tokenizer."""
    from transformers import AutoTokenizer  # type: ignore

    tokenizer = AutoTokenizer.from_pretrained(model_id)

    def count(text: str) -> int:
        return len(tokenizer(text, add_special_tokens=False)["input_ids"])

    return count, tokenizer


# ---------- splitting helpers ----------

_SEPARATORS = ["\n\n", "\n", ". ", " "]


def _split_on(text: str, sep: str) -> list[str]:
    if sep == " ":
        return text.split(" ")
    parts = text.split(sep)
    if sep == ". ":
        # Re-attach the period we used as separator (except possibly the last piece).
        return [p + ("." if i < len(parts) - 1 else "") for i, p in enumerate(parts)]
    # Re-attach the separator so we can rebuild text faithfully.
    return [p + sep for p in parts[:-1]] + ([parts[-1]] if parts[-1] else [])


def _atomic_pieces(text: str) -> list[str]:
    """Walk through separators until pieces fit individual tokenization.

    The chunker greedily packs these pieces; final hard-cap truncation in
    ``_pack`` handles any remaining oversize piece.
    """
    queue: list[str] = [text]
    for sep in _SEPARATORS:
        next_queue: list[str] = []
        any_split = False
        for piece in queue:
            if sep in piece and len(piece) > 0:
                next_queue.extend(_split_on(piece, sep))
                any_split = True
            else:
                next_queue.append(piece)
        queue = [p for p in next_queue if p]
        if not any_split:
            break
    return queue


def _pack(
    pieces: list[str],
    *,
    count: TokenCounter,
    target: int,
    max_tokens: int,
    overlap: int,
) -> list[tuple[str, int, bool]]:
    """Pack atomic pieces into chunks. Returns list of (text, token_count, truncated)."""
    chunks: list[tuple[str, int, bool]] = []
    current = ""
    current_tokens = 0

    def flush() -> None:
        nonlocal current, current_tokens
        if not current.strip():
            current, current_tokens = "", 0
            return
        text = current
        tc = current_tokens
        truncated = False
        if tc > max_tokens:
            # Hard cap — truncate to max_tokens by binary trimming on words.
            words = text.split(" ")
            lo, hi = 0, len(words)
            while lo < hi:
                mid = (lo + hi + 1) // 2
                if count(" ".join(words[:mid])) <= max_tokens:
                    lo = mid
                else:
                    hi = mid - 1
            text = " ".join(words[:lo])
            tc = count(text)
            truncated = True
            log.warning("chunk truncated from %d to %d tokens", current_tokens, tc)
        chunks.append((text, tc, truncated))

    for piece in pieces:
        piece_tokens = count(piece) if piece else 0
        if current_tokens + piece_tokens <= target or not current:
            current += piece
            current_tokens += piece_tokens
        else:
            flush()
            # Build overlap tail of the previous chunk to seed the next one.
            tail = ""
            if overlap > 0 and chunks:
                prev_text = chunks[-1][0]
                words = prev_text.split(" ")
                # Walk from the end until we have ~overlap tokens.
                lo = len(words)
                while lo > 0 and count(" ".join(words[lo - 1 :])) <= overlap:
                    lo -= 1
                tail = " ".join(words[lo:])
                if tail and not tail.endswith(" "):
                    tail += " "
            current = tail + piece
            current_tokens = count(current)

    flush()
    return chunks


def _split_table(
    text: str,
    *,
    count: TokenCounter,
    max_tokens: int,
) -> list[tuple[str, int, bool]]:
    """Tables: keep whole if it fits, else split by row-groups with header repeated."""
    total = count(text)
    if total <= max_tokens:
        return [(text, total, False)]

    lines = text.split("\n")
    # Detect markdown table header (first two lines starting with "|").
    header_lines: list[str] = []
    body_start = 0
    if (
        len(lines) >= 2
        and lines[0].lstrip().startswith("|")
        and re.match(r"^\s*\|[\s\-|]+\|\s*$", lines[1])
    ):
        header_lines = lines[:2]
        body_start = 2
    # Allow leading non-table preamble (e.g. "## Section\n\n") to be header too.
    elif len(lines) >= 4 and lines[2].lstrip().startswith("|") and re.match(
        r"^\s*\|[\s\-|]+\|\s*$", lines[3]
    ):
        header_lines = lines[:4]
        body_start = 4

    if not header_lines:
        # No detectable header — fall back to prose splitter.
        return _pack(
            _atomic_pieces(text),
            count=count,
            target=max_tokens,
            max_tokens=max_tokens,
            overlap=0,
        )

    header_text = "\n".join(header_lines)
    header_tokens = count(header_text)

    chunks: list[tuple[str, int, bool]] = []
    current_rows: list[str] = []
    current_tokens = header_tokens

    def flush_rows() -> None:
        nonlocal current_rows, current_tokens
        if not current_rows:
            return
        text_out = header_text + "\n" + "\n".join(current_rows)
        tc = count(text_out)
        chunks.append((text_out, tc, False))
        current_rows, current_tokens = [], header_tokens

    for row in lines[body_start:]:
        if not row.strip():
            continue
        row_tokens = count(row)
        if current_tokens + row_tokens > max_tokens and current_rows:
            flush_rows()
        current_rows.append(row)
        current_tokens += row_tokens
    flush_rows()
    return chunks


# ---------- chunk record assembly ----------


def _sha256(s: str) -> str:
    return "sha256:" + hashlib.sha256(s.encode("utf-8")).hexdigest()


def _chunk_id(source_url: str, section_id: str, idx: int, text_hash: str) -> str:
    raw = f"{source_url}::{section_id}::{idx}::{text_hash}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:16]


def chunk_section(
    section: dict[str, Any],
    *,
    parent: dict[str, Any],
    run_id: str,
    count: TokenCounter,
    target: int,
    max_tokens: int,
    overlap: int,
) -> tuple[list[ChunkRecord], int]:
    """Split one section into chunk records. Returns (chunks, truncated_count)."""
    title = section.get("section_title") or section["section_id"]
    body = section.get("text") or ""
    if not body.strip():
        return [], 0

    prefix = f"## {title}\n\n"
    full_text = prefix + body
    kind = section.get("kind", "prose")

    if kind == "table":
        pieces = _split_table(full_text, count=count, max_tokens=max_tokens)
    else:
        pieces = _pack(
            _atomic_pieces(full_text),
            count=count,
            target=target,
            max_tokens=max_tokens,
            overlap=overlap if kind == "prose" else 0,
        )

    records: list[ChunkRecord] = []
    truncated = 0
    for idx, (text, token_count, was_truncated) in enumerate(pieces):
        text_hash = _sha256(text)
        chunk_id = _chunk_id(parent["source_url"], section["section_id"], idx, text_hash)
        metadata = {
            "source_url": parent["source_url"],
            "source_type": parent.get("source_type", "groww_scheme_page"),
            "scheme_id": parent["scheme_id"],
            "scheme_name": parent["scheme_name"],
            "amc": parent["amc"],
            "section_id": section["section_id"],
            "section_title": title,
            "kind": kind,
            "chunk_index": idx,
            "fetched_at": parent["fetched_at"],
            "run_id": run_id,
        }
        records.append(
            ChunkRecord(
                chunk_id=chunk_id,
                chunk_text=text,
                chunk_text_hash=text_hash,
                token_count=token_count,
                metadata=metadata,
            )
        )
        if was_truncated:
            truncated += 1
    return records, truncated


# ---------- run-level orchestration ----------


def _now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def chunk_all(
    normalized_run_dir: Path,
    chunks_root: Path,
    *,
    model_id: str = DEFAULT_MODEL_ID,
    target_tokens: int = DEFAULT_TARGET_TOKENS,
    max_tokens: int = DEFAULT_MAX_TOKENS,
    overlap_tokens: int = DEFAULT_OVERLAP_TOKENS,
    token_counter: TokenCounter | None = None,
) -> tuple[Path, ChunkRunStats]:
    run_id = normalized_run_dir.name
    chunks_run_dir = Path(chunks_root) / run_id
    chunks_run_dir.mkdir(parents=True, exist_ok=True)

    count = token_counter or make_token_counter(model_id)[0]

    out_path = chunks_run_dir / "chunks.jsonl"
    results: list[SchemeChunkResult] = []
    total_chunks = 0
    total_truncated = 0

    with out_path.open("w", encoding="utf-8") as out_fh:
        for normalized_path in sorted(normalized_run_dir.glob("*.json")):
            if normalized_path.name == "manifest.json":
                continue
            try:
                doc = json.loads(normalized_path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                results.append(
                    SchemeChunkResult(
                        scheme_id=normalized_path.stem,
                        status="failed",
                        chunk_count=0,
                        error=f"read/parse: {exc}",
                    )
                )
                continue

            scheme_id = doc.get("scheme_id") or normalized_path.stem
            scheme_chunks = 0
            scheme_truncated = 0
            try:
                for section in doc.get("sections", []):
                    records, truncated = chunk_section(
                        section,
                        parent=doc,
                        run_id=run_id,
                        count=count,
                        target=target_tokens,
                        max_tokens=max_tokens,
                        overlap=overlap_tokens,
                    )
                    for rec in records:
                        out_fh.write(json.dumps(asdict(rec), ensure_ascii=False) + "\n")
                    scheme_chunks += len(records)
                    scheme_truncated += truncated
            except Exception as exc:  # noqa: BLE001
                log.warning("chunk failed for %s: %s", scheme_id, exc)
                results.append(
                    SchemeChunkResult(
                        scheme_id=scheme_id,
                        status="failed",
                        chunk_count=scheme_chunks,
                        error=str(exc),
                    )
                )
                continue

            results.append(
                SchemeChunkResult(
                    scheme_id=scheme_id,
                    status="ok",
                    chunk_count=scheme_chunks,
                )
            )
            total_chunks += scheme_chunks
            total_truncated += scheme_truncated

    stats = ChunkRunStats(
        run_id=run_id,
        total_schemes=len(results),
        ok_schemes=sum(1 for r in results if r.status == "ok"),
        failed_schemes=sum(1 for r in results if r.status == "failed"),
        total_chunks=total_chunks,
        truncated_chunks=total_truncated,
        results=results,
    )

    manifest = {
        "run_id": run_id,
        "phase": "4.1_chunk",
        "embedding_model_id": model_id,
        "target_tokens": target_tokens,
        "max_tokens": max_tokens,
        "overlap_tokens": overlap_tokens,
        "finished_at": _now_iso(),
        "total_schemes": stats.total_schemes,
        "ok_schemes": stats.ok_schemes,
        "failed_schemes": stats.failed_schemes,
        "total_chunks": stats.total_chunks,
        "truncated_chunks": stats.truncated_chunks,
        "results": [asdict(r) for r in results],
    }
    (chunks_run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    return chunks_run_dir, stats
