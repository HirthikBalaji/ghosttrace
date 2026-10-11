"""Bitemporal semantics (§3.1).

Storage: UTC epoch milliseconds (int). Intervals are half-open [from, to).
  Visible(f, tau)          <=> tx_from <= tau < tx_to            (tx_to null = still current)
  Active(f, T, tau)        <=> Visible and valid_from <= T < valid_to   (validity known)
  ActiveUncertain(f, T, t) <=> Visible and validity_unknown and not provably inactive at T

`validity_unknown` is set at ingestion when valid_from is missing, or valid_to is missing and
the source did not assert `valid_open_ended`. It is uncertainty, never silently "valid".

The Cypher predicate below is a constant string; (T, tau) always travel as parameters. The
Python mirror `temporal_status` implements the same rule and is differential-tested against it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Any

from pydantic import AwareDatetime, TypeAdapter


class TemporalStatus(StrEnum):
    INVISIBLE = "INVISIBLE"  # not known as of tau
    INACTIVE = "INACTIVE"  # known, but not valid at T
    ACTIVE = "ACTIVE"
    UNCERTAIN = "UNCERTAIN"  # known, validity interval not established


# Shared temporal predicate for every path, blast-radius, ownership and brain query.
# `r` is the relationship variable; parameters: $T (world time), $tau (knowledge time).
TEMPORAL_PREDICATE = (
    "(r.tx_from <= $tau AND (r.tx_to IS NULL OR $tau < r.tx_to)"
    " AND (r.valid_to IS NULL OR $T < r.valid_to)"
    " AND (r.valid_from IS NULL OR r.valid_from <= $T))"
)
TEMPORAL_STATUS_EXPR = "CASE WHEN r.validity_unknown THEN 'UNCERTAIN' ELSE 'ACTIVE' END"


def temporal_predicate(var: str = "r") -> str:
    """Return the constant predicate text bound to relationship variable `var` (identifier only)."""
    if not var.isidentifier():
        raise ValueError("invalid Cypher variable")
    return TEMPORAL_PREDICATE.replace("r.", f"{var}.")


def validity_unknown(valid_from: int | None, valid_to: int | None, valid_open_ended: bool) -> bool:
    return valid_from is None or (valid_to is None and not valid_open_ended)


def is_visible(tx_from: int, tx_to: int | None, tau: int) -> bool:
    return tx_from <= tau and (tx_to is None or tau < tx_to)


def temporal_status(f: dict[str, Any] | Any, T: int, tau: int) -> TemporalStatus:
    g = (lambda k: f.get(k)) if isinstance(f, dict) else (lambda k: getattr(f, k))
    if not is_visible(g("tx_from"), g("tx_to"), tau):
        return TemporalStatus.INVISIBLE
    vf, vt = g("valid_from"), g("valid_to")
    if vt is not None and not T < vt:
        return TemporalStatus.INACTIVE
    if vf is not None and not vf <= T:
        return TemporalStatus.INACTIVE
    if g("validity_unknown"):
        return TemporalStatus.UNCERTAIN
    return TemporalStatus.ACTIVE


_aware = TypeAdapter(AwareDatetime)


def parse_iso(value: str | int) -> int:
    """API boundary: ISO-8601 with explicit offset (or epoch ms int) -> UTC epoch ms. Naive rejected."""
    if isinstance(value, bool):
        raise ValueError("boolean is not a timestamp")
    if isinstance(value, int):
        return value
    dt = _aware.validate_python(value)  # raises on naive datetimes
    return int(dt.astimezone(UTC).timestamp() * 1000)


def to_iso(ms: int | None) -> str | None:
    if ms is None:
        return None
    return datetime.fromtimestamp(ms / 1000, tz=UTC).isoformat().replace("+00:00", "Z")
