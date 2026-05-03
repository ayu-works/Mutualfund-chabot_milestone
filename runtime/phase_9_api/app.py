"""Phase 9 — FastAPI application.

See docs/rag-architecture.md §9.

Endpoints:
* GET  /health
* POST /threads
* GET  /threads
* GET  /threads/{id}/messages
* POST /threads/{id}/messages   → phase 8 post_user_message
* POST /admin/reindex           → 501 stub, gated by ADMIN_REINDEX_SECRET
* GET  /                        → JSON pointers (docs, web UI)
* GET  /ui                      → static HTML test client served from web/

`RUNTIME_API_DEBUG=1` enables the per-message `debug` payload (latency,
generation metadata, route reason, validation errors). Off by default
per §9.2 leakage guidance.
"""
from __future__ import annotations

import logging
import os
import time
from pathlib import Path
from typing import Any

from fastapi import FastAPI, Header, HTTPException, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from runtime.phase_7_safety import SafetyPipeline
from runtime.phase_8_threads import ThreadedChat, ThreadStore

log = logging.getLogger(__name__)


# ---------- request / response models ----------


class CreateThreadRequest(BaseModel):
    session_key: str | None = Field(default=None, max_length=128)


class CreateThreadResponse(BaseModel):
    thread_id: str
    session_key: str | None
    created_at: str


class ThreadListItem(BaseModel):
    thread_id: str
    session_key: str | None
    created_at: str


class MessageOut(BaseModel):
    role: str
    content: str
    timestamp: str
    retrieval_debug_id: str | None = None


class PostMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=4000)
    use_query_expansion: bool = True


class PostMessageDebug(BaseModel):
    latency_ms: int
    route_reason: str
    refused: bool
    used_fallback: bool
    retried: bool
    validation_errors: list[str]
    model: str
    citation_url: str | None
    footer_date: str | None


class PostMessageResponse(BaseModel):
    assistant_message: str
    citation_url: str | None
    footer_date: str | None
    debug: PostMessageDebug | None = None


# ---------- factory ----------


def _debug_enabled() -> bool:
    return os.getenv("RUNTIME_API_DEBUG", "0").strip() in {"1", "true", "True"}


def _web_dir() -> Path:
    # Next.js static export output (run `npm run build` in web/ to populate)
    return Path(__file__).resolve().parents[2] / "web" / "out"


def create_app(
    *,
    store: ThreadStore | None = None,
    pipeline: SafetyPipeline | None = None,
) -> FastAPI:
    app = FastAPI(
        title="Mutual Fund FAQ Assistant",
        description=(
            "Facts-only RAG API over 5 HDFC scheme pages. "
            "See docs/rag-architecture.md §9."
        ),
        version="0.1.0",
    )

    # CORS so the static UI in web/ can call the API from a different origin
    # during local dev (e.g. `python -m http.server 5500` opening web/index.html).
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    _store = store or ThreadStore()
    _chat = ThreadedChat(store=_store, pipeline=pipeline)

    @app.get("/")
    def root() -> dict[str, Any]:
        return {
            "name": "mf-faq-assistant",
            "docs": "/docs",
            "openapi": "/openapi.json",
            "ui": "/ui",
            "health": "/health",
            "architecture": "docs/rag-architecture.md",
        }

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    web_dir = _web_dir()
    if web_dir.exists():
        # Mount static assets (style.css, app.js) under /ui/*; index.html is
        # served by the explicit /ui handler so SPA-style refreshes work.
        app.mount("/ui", StaticFiles(directory=str(web_dir), html=True), name="ui")

    @app.post(
        "/threads",
        response_model=CreateThreadResponse,
        status_code=status.HTTP_201_CREATED,
    )
    def create_thread(req: CreateThreadRequest | None = None) -> CreateThreadResponse:
        body = req or CreateThreadRequest()
        t = _store.create_thread(session_key=body.session_key)
        return CreateThreadResponse(**t.to_dict())

    @app.get("/threads", response_model=list[ThreadListItem])
    def list_threads(
        session_key: str | None = None,
        limit: int = 50,
    ) -> list[ThreadListItem]:
        threads = _store.list_threads(session_key=session_key, limit=limit)
        return [ThreadListItem(**t.to_dict()) for t in threads]

    @app.get("/threads/{thread_id}/messages", response_model=list[MessageOut])
    def get_messages(thread_id: str) -> list[MessageOut]:
        if _store.get_thread(thread_id) is None:
            raise HTTPException(status_code=404, detail="thread not found")
        msgs = _store.history(thread_id)
        # §9.2: never expose retrieval_debug_id when debug mode is off.
        if not _debug_enabled():
            return [
                MessageOut(role=m.role, content=m.content, timestamp=m.timestamp)
                for m in msgs
            ]
        return [MessageOut(**m.to_dict()) for m in msgs]

    @app.delete("/threads/{thread_id}")
    def delete_thread(thread_id: str) -> Response:
        deleted = _store.delete_thread(thread_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="thread not found")
        return Response(status_code=204)

    @app.post(
        "/threads/{thread_id}/messages",
        response_model=PostMessageResponse,
    )
    def post_message(
        thread_id: str, req: PostMessageRequest
    ) -> PostMessageResponse:
        if _store.get_thread(thread_id) is None:
            raise HTTPException(status_code=404, detail="thread not found")

        t0 = time.perf_counter()
        result = _chat.post_user_message(
            thread_id,
            req.content,
            use_query_expansion=req.use_query_expansion,
        )
        latency_ms = int((time.perf_counter() - t0) * 1000)

        debug: PostMessageDebug | None = None
        if _debug_enabled():
            debug = PostMessageDebug(
                latency_ms=latency_ms,
                route_reason=result.route_reason,
                refused=result.refused,
                used_fallback=result.used_fallback,
                retried=result.retried,
                validation_errors=list(result.validation_errors),
                model=result.model,
                citation_url=result.citation_url,
                footer_date=result.footer_date,
            )

        return PostMessageResponse(
            assistant_message=result.answer,
            citation_url=result.citation_url,
            footer_date=result.footer_date,
            debug=debug,
        )

    @app.post("/admin/reindex")
    def admin_reindex(
        x_admin_secret: str | None = Header(default=None, alias="X-Admin-Secret"),
    ) -> JSONResponse:
        expected = os.getenv("ADMIN_REINDEX_SECRET", "")
        if not expected:
            raise HTTPException(
                status_code=503,
                detail="ADMIN_REINDEX_SECRET not configured",
            )
        if x_admin_secret != expected:
            raise HTTPException(status_code=401, detail="invalid admin secret")
        # Stub per architecture §9.1 — daily ingest is the GitHub Actions job.
        return JSONResponse(
            status_code=501,
            content={
                "status": "not_implemented",
                "hint": (
                    "Trigger ingest via GitHub Actions workflow_dispatch on "
                    ".github/workflows/ingest.yml. CLI on the host can also "
                    "run `python -m ingest.phase_4_3_index --run-id ...`."
                ),
            },
        )

    return app


# Module-level app for `uvicorn runtime.phase_9_api.app:app`.
app = create_app()
