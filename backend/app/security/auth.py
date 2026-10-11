"""Pluggable auth abstraction. ONLY a demo-grade mode exists in this build — it is NOT production auth.

`demo_header`: requests must send `X-GT-Demo-Token` equal to GT_DEMO_TOKEN (constant-time compare).
If GT_DEMO_TOKEN is unset the API fails closed (401). `disabled_local` is accepted only when
GT_ENV=local and is intended for a trusted single-user laptop. There is no OIDC; do not deploy beyond a
trusted local environment.
"""

from __future__ import annotations

import hmac
import re
from dataclasses import dataclass

from fastapi import Header, HTTPException, Request

from app.config import get_settings
from app.graph.client import WORKSPACE_RE


@dataclass(frozen=True)
class Principal:
    subject: str
    workspace_id: str
    mode: str


_SUBJECT_RE = re.compile(r"^[A-Za-z0-9_.@-]{1,64}$")


def authenticate(
    request: Request,
    x_gt_demo_token: str | None = Header(default=None),
    x_gt_workspace: str | None = Header(default=None),
    x_gt_user: str | None = Header(default=None),
) -> Principal:
    s = get_settings()
    ws = x_gt_workspace or "demo"
    if not WORKSPACE_RE.fullmatch(ws):
        raise HTTPException(status_code=400, detail="invalid workspace id")
    subject = x_gt_user if x_gt_user and _SUBJECT_RE.fullmatch(x_gt_user) else "demo-user"
    if s.auth_mode == "disabled_local":
        if s.env != "local":
            raise HTTPException(status_code=401, detail="auth disabled outside local env is not allowed")
        return Principal(subject, ws, "disabled_local")
    if not s.demo_token:
        raise HTTPException(status_code=401, detail="demo auth not configured (GT_DEMO_TOKEN unset): failing closed")
    if not x_gt_demo_token or not hmac.compare_digest(x_gt_demo_token.encode(), s.demo_token.encode()):
        raise HTTPException(status_code=401, detail="missing or invalid demo token")
    return Principal(subject, ws, "demo_header")
