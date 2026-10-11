"""FastAPI application: GHOSTTRACE (synthetic demo build)."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from collections import Counter
from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, PlainTextResponse, Response

from app.api.routes import router
from app.audit.logging import configure, request_id_var
from app.config import get_settings
from app.graph.client import get_client
from app.graph.repository import Repository
from app.graph.schema import CURRENT_SCHEMA_VERSION, current_version
from app.orchestration.orchestrator import resume_stale

log = logging.getLogger("ghosttrace.api")
METRICS: Counter[str] = Counter()
MAX_BODY = 256 * 1024


def _resume_all() -> None:
    try:
        c = get_client()
        for ws in c.list_workspaces():
            resumed = resume_stale(Repository(c, ws))
            if resumed:
                log.info(f"resumed investigations in {ws}: {resumed}")
    except Exception as exc:  # readiness reports DB problems; startup must not crash
        log.warning(f"resume on startup skipped: {type(exc).__name__}")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure(get_settings().log_level)
    threading.Thread(target=_resume_all, daemon=True, name="gt-resume").start()
    yield
    log.info("shutdown: draining")


app = FastAPI(title="GHOSTTRACE API", version="0.1.0", lifespan=lifespan,
              description="Open-world containment over a bitemporal FalkorDB graph. SYNTHETIC DEMO: all actions "
                          "are simulations. Demo-only auth (X-GT-Demo-Token); not production authentication.")
s = get_settings()
app.add_middleware(CORSMiddleware, allow_origins=[o.strip() for o in s.cors_origins.split(",") if o.strip()],
                   allow_methods=["GET", "POST"], allow_headers=["X-GT-Demo-Token", "X-GT-Workspace", "X-GT-User",
                                                                  "Content-Type"], allow_credentials=False)

SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff", "X-Frame-Options": "DENY", "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": "default-src 'none'; frame-ancestors 'none'",
    "Cache-Control": "no-store",
}


@app.middleware("http")
async def context(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    rid = request.headers.get("X-Request-ID", "")[:64] or uuid.uuid4().hex[:16]
    request_id_var.set(rid)
    if int(request.headers.get("content-length") or 0) > MAX_BODY:
        return JSONResponse({"error": {"code": "payload_too_large", "message": "request body too large"},
                             "meta": {"request_id": rid}}, status_code=413)
    t0 = time.monotonic()
    resp = await call_next(request)
    ms = round((time.monotonic() - t0) * 1000, 2)
    METRICS["requests_total"] += 1
    METRICS[f"status_{resp.status_code // 100}xx"] += 1
    METRICS["latency_ms_sum"] += int(ms)
    resp.headers["X-Request-ID"] = rid
    for k, v in SECURITY_HEADERS.items():
        if k == "Content-Security-Policy" and request.url.path in ("/docs", "/redoc"):
            continue
        resp.headers.setdefault(k, v)
    log.info("request", extra={"path": request.url.path, "method": request.method, "status": resp.status_code, "ms": ms})
    return resp


def _err(code: str, message: str, status: int, details: Any = None) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message, "details": details},
                         "meta": {"request_id": request_id_var.get()}}, status_code=status)


@app.exception_handler(HTTPException)
async def http_exc(_: Request, exc: HTTPException) -> JSONResponse:
    return _err({401: "unauthorized", 404: "not_found", 422: "invalid_input", 429: "rate_limited"}.get(exc.status_code, "error"),
                str(exc.detail), exc.status_code)


@app.exception_handler(RequestValidationError)
async def val_exc(_: Request, exc: RequestValidationError) -> JSONResponse:
    details = [{"loc": list(e.get("loc", [])), "msg": e.get("msg")} for e in exc.errors()]
    return _err("invalid_input", "request validation failed", 422, details)


@app.exception_handler(Exception)
async def any_exc(_: Request, exc: Exception) -> JSONResponse:
    log.error(f"unhandled {type(exc).__name__}")  # no stack traces or values in responses
    return _err("internal_error", "internal error; see server logs with this request id", 500)


@app.get("/health")
def health() -> dict[str, Any]:
    """Liveness: no graph dependency."""
    return {"status": "ok", "synthetic": True}


@app.get("/ready")
def ready() -> JSONResponse:
    """Readiness: FalkorDB reachable and schema known. Never returns connection details or secrets."""
    c = get_client()
    db_ok = c.ping()
    checks: dict[str, Any] = {"falkordb": db_ok, "required_schema_version": CURRENT_SCHEMA_VERSION}
    if db_ok:
        try:
            checks["workspaces"] = {ws: current_version(c, ws) for ws in c.list_workspaces()}
        except Exception:
            checks["workspaces"] = "unavailable"
    return JSONResponse({"status": "ready" if db_ok else "not_ready", "checks": checks}, status_code=200 if db_ok else 503)


@app.get("/metrics", response_class=PlainTextResponse)
def metrics() -> str:
    return "\n".join(f"ghosttrace_{k} {v}" for k, v in sorted(METRICS.items())) + "\n"


app.include_router(router, prefix="/api/v1")
