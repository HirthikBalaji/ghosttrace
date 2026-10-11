"""Authentication and authorisation.

Modes (GT_AUTH_MODE):
  * `oidc` (production): `Authorization: Bearer <JWT>` from an OpenID Connect provider. Signature is checked
    against the provider's JWKS (`GT_OIDC_JWKS_URL`, or a pinned `GT_OIDC_JWKS_JSON`), with an allowlist of
    asymmetric algorithms, and `iss`, `aud`, `exp`, `iat`, `sub` are required. Roles come from
    `GT_OIDC_ROLES_CLAIM` and permitted workspaces from `GT_OIDC_WORKSPACES_CLAIM` (`"*"` = all).
  * `demo_header` (local/test/ci only): shared `X-GT-Demo-Token`, constant-time compared, fails closed when unset.
  * `disabled_local` (GT_ENV=local only): single trusted laptop.

GT_ENV=production refuses any mode other than `oidc` (checked at startup and on every request).

Permissions: read (viewer+), operate (analyst/admin: create, run, cancel, simulate, verify),
approve (approver/admin), admin (admin: reset/seed workspaces).
"""

from __future__ import annotations

import hmac
import json
import re
import threading
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import jwt
from fastapi import Depends, Header, HTTPException

from app.config import Settings, get_settings
from app.graph.client import WORKSPACE_RE

ROLES = ("viewer", "analyst", "approver", "admin")
PERMISSIONS: dict[str, frozenset[str]] = {
    "read": frozenset(ROLES),
    "operate": frozenset({"analyst", "admin"}),
    "approve": frozenset({"approver", "admin"}),
    "admin": frozenset({"admin"}),
}
ASYMMETRIC_ALGS = frozenset({"RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512", "EdDSA"})
_SUBJECT_RE = re.compile(r"^[A-Za-z0-9_.@|:+-]{1,128}$")


class AuthConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Principal:
    subject: str
    workspace_id: str
    mode: str
    roles: frozenset[str] = field(default_factory=frozenset)

    def can(self, permission: str) -> bool:
        return bool(self.roles & PERMISSIONS[permission])


def check_settings(s: Settings) -> None:
    """Fail closed on unsafe combinations. Called at startup and per request."""
    if s.env == "production" and s.auth_mode != "oidc":
        raise AuthConfigError("GT_ENV=production requires GT_AUTH_MODE=oidc")
    if s.auth_mode == "disabled_local" and s.env != "local":
        raise AuthConfigError("GT_AUTH_MODE=disabled_local is only allowed with GT_ENV=local")
    if s.auth_mode == "oidc":
        if not (s.oidc_issuer and s.oidc_audience and (s.oidc_jwks_url or s.oidc_jwks_json)):
            raise AuthConfigError("oidc mode needs GT_OIDC_ISSUER, GT_OIDC_AUDIENCE and GT_OIDC_JWKS_URL/GT_OIDC_JWKS_JSON")
        algs = {a.strip() for a in s.oidc_algorithms.split(",") if a.strip()}
        if not algs or not algs <= ASYMMETRIC_ALGS:
            raise AuthConfigError("GT_OIDC_ALGORITHMS must be a non-empty list of asymmetric algorithms")
        if s.env == "production" and s.oidc_jwks_url and not s.oidc_jwks_url.startswith("https://"):
            raise AuthConfigError("GT_OIDC_JWKS_URL must be https in production")


class _KeyResolver:
    """Resolves the signing key for a token from a JWKS URL (cached) or a pinned JWKS document."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._cache: dict[tuple[str | None, str | None], Callable[[str], Any]] = {}

    def get(self, s: Settings) -> Callable[[str], Any]:
        key = (s.oidc_jwks_url, s.oidc_jwks_json)
        with self._lock:
            if key not in self._cache:
                if s.oidc_jwks_json:
                    jwks = jwt.PyJWKSet.from_dict(json.loads(s.oidc_jwks_json))

                    def by_kid(token: str, jwks: jwt.PyJWKSet = jwks) -> Any:
                        kid = jwt.get_unverified_header(token).get("kid")
                        for k in jwks.keys:
                            if kid is None or k.key_id == kid:
                                return k.key
                        raise jwt.InvalidTokenError("no matching key")

                    self._cache[key] = by_kid
                else:
                    client = jwt.PyJWKClient(str(s.oidc_jwks_url), cache_keys=True, lifespan=300, timeout=5)
                    self._cache[key] = lambda token: client.get_signing_key_from_jwt(token).key
            return self._cache[key]

    def clear(self) -> None:
        with self._lock:
            self._cache.clear()


keys = _KeyResolver()


def _claim_list(claims: dict[str, Any], path: str) -> list[str]:
    cur: Any = claims
    for part in path.split("."):  # supports nested claims such as realm_access.roles
        cur = cur.get(part) if isinstance(cur, dict) else None
    if isinstance(cur, str):
        return cur.split()
    return [str(x) for x in cur] if isinstance(cur, list) else []


def verify_bearer(token: str, s: Settings) -> dict[str, Any]:
    algs = sorted(a.strip() for a in s.oidc_algorithms.split(",") if a.strip())
    try:
        header = jwt.get_unverified_header(token)
        if header.get("alg") not in algs:
            raise jwt.InvalidAlgorithmError("algorithm not allowed")
        claims: dict[str, Any] = jwt.decode(
            token,
            keys.get(s)(token),
            algorithms=algs,
            audience=s.oidc_audience,
            issuer=s.oidc_issuer,
            leeway=30,
            options={"require": ["exp", "iat", "iss", "aud", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise HTTPException(status_code=401, detail=f"invalid bearer token ({type(exc).__name__})") from exc
    return claims


def authenticate(
    authorization: str | None = Header(default=None),
    x_gt_demo_token: str | None = Header(default=None),
    x_gt_workspace: str | None = Header(default=None),
    x_gt_user: str | None = Header(default=None),
) -> Principal:
    s = get_settings()
    try:
        check_settings(s)
    except AuthConfigError as exc:
        raise HTTPException(status_code=401, detail=f"auth misconfigured, failing closed: {exc}") from exc
    ws = x_gt_workspace or "demo"
    if not WORKSPACE_RE.fullmatch(ws):
        raise HTTPException(status_code=400, detail="invalid workspace id")

    if s.auth_mode == "oidc":
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="missing bearer token")
        claims = verify_bearer(authorization[7:].strip(), s)
        subject = str(claims.get(s.oidc_subject_claim) or claims["sub"])
        if not _SUBJECT_RE.fullmatch(subject):
            raise HTTPException(status_code=401, detail="invalid subject claim")
        roles = frozenset(r for r in _claim_list(claims, s.oidc_roles_claim) if r in ROLES)
        if not roles:
            raise HTTPException(status_code=403, detail="token carries no GHOSTTRACE role")
        allowed = _claim_list(claims, s.oidc_workspaces_claim)
        if "*" not in allowed and ws not in allowed:
            raise HTTPException(status_code=403, detail="workspace not permitted for this principal")
        return Principal(subject, ws, "oidc", roles)

    subject = x_gt_user if x_gt_user and _SUBJECT_RE.fullmatch(x_gt_user) else "demo-user"
    if s.auth_mode == "disabled_local":
        return Principal(subject, ws, "disabled_local", frozenset(ROLES))
    if not s.demo_token:
        raise HTTPException(status_code=401, detail="demo auth not configured (GT_DEMO_TOKEN unset): failing closed")
    if not x_gt_demo_token or not hmac.compare_digest(x_gt_demo_token.encode(), s.demo_token.encode()):
        raise HTTPException(status_code=401, detail="missing or invalid demo token")
    return Principal(subject, ws, "demo_header", frozenset(ROLES))


def require(permission: str) -> Callable[..., Principal]:
    if permission not in PERMISSIONS:
        raise ValueError(f"unknown permission {permission}")

    def dep(p: Principal = Depends(authenticate)) -> Principal:  # noqa: B008
        if not p.can(permission):
            raise HTTPException(status_code=403, detail=f"requires '{permission}' permission")
        return p

    return dep
