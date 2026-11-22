"""Pure logic: names, expiry tags, cost estimates. No network, easy to test."""

from __future__ import annotations

import re
from datetime import datetime, timezone

MARK_TAG = "dofleet"
EXP_PREFIX = "dofleet-exp-"
PRESET_PREFIX = "dofleet-preset-"
HOURS_PER_MONTH = 672  # DigitalOcean caps hourly billing at 672 h (28 days) per month

class DurationError(ValueError):
    pass


_DURATION = re.compile(r"^\s*(\d+)\s*([mhdw])\s*$", re.I)
_UNIT = {"m": 60, "h": 3600, "d": 86400, "w": 604800}


def parse_duration(text: str) -> int:
    """'30m' / '2h' / '3d' / '1w' -> seconds. Raises ValueError."""
    m = _DURATION.match(text or "")
    if not m or int(m.group(1)) <= 0:
        raise DurationError(text)
    return int(m.group(1)) * _UNIT[m.group(2).lower()]


def format_duration(seconds: float) -> str:
    seconds = int(seconds)
    sign = "-" if seconds < 0 else ""
    seconds = abs(seconds)
    d, rem = divmod(seconds, 86400)
    h, rem = divmod(rem, 3600)
    m = rem // 60
    if d:
        return f"{sign}{d}d{h}h"
    if h:
        return f"{sign}{h}h{m:02d}m"
    return f"{sign}{m}m"


def mem_text(mb) -> str:
    mb = int(mb or 0)
    return f"{mb // 1024} GB" if mb >= 1024 else f"{mb} MB"


def sanitize_name(name: str) -> str:
    out = re.sub(r"[^a-zA-Z0-9.-]", "-", name or "")
    out = re.sub(r"-+", "-", out).strip("-.")
    return out[:63] or "droplet"


def tag_safe(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]", "-", text)[:200]


def numbered_names(prefix: str, count: int, taken: set[str]) -> list[str]:
    """prefix-01, prefix-02 ... skipping names that already exist. count == 1 -> plain prefix if free."""
    base = sanitize_name(prefix)
    if count == 1 and base not in taken:
        return [base]
    names, i = [], 1
    while len(names) < count:
        cand = f"{base}-{i:02d}"
        if cand not in taken:
            names.append(cand)
        i += 1
    return names


def expiry_tag(now: float, ttl_seconds: int) -> str:
    return f"{EXP_PREFIX}{int(now + ttl_seconds)}"


def expires_at(droplet: dict) -> int | None:
    stamps = [int(t[len(EXP_PREFIX):]) for t in droplet.get("tags", [])
              if t.startswith(EXP_PREFIX) and t[len(EXP_PREFIX):].isdigit()]
    return min(stamps) if stamps else None


def is_managed(droplet: dict) -> bool:
    return MARK_TAG in droplet.get("tags", [])


def expired(droplets: list[dict], now: float) -> list[dict]:
    return [d for d in droplets if (exp := expires_at(d)) is not None and exp <= now]


def created_ts(droplet: dict) -> float:
    raw = droplet.get("created_at") or ""
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).timestamp()
    except ValueError:
        return datetime.now(timezone.utc).timestamp()


def prices(droplet: dict) -> tuple[float, float]:
    size = droplet.get("size") or {}
    return float(size.get("price_hourly") or 0), float(size.get("price_monthly") or 0)


def accrued(droplet: dict, now: float) -> float:
    """Estimated spend so far for this droplet: hours alive x hourly rate, capped at the monthly price.
    Rough by design: it ignores month boundaries, backups and bandwidth overage."""
    hourly, monthly = prices(droplet)
    hours = max(0.0, (now - created_ts(droplet)) / 3600)
    return min(hours * hourly, monthly) if monthly else hours * hourly


def batch_cost(hourly: float, monthly: float, count: int, ttl_seconds: int | None) -> tuple[float, float]:
    """(cost if it lives until its expiry timer, cost for a full month)."""
    full = monthly * count
    if ttl_seconds is None:
        return full, full
    hours = ttl_seconds / 3600
    return min(hours * hourly, monthly) * count, full


def match(droplets: list[dict], patterns: list[str]) -> list[dict]:
    """Match by exact id, exact name, or shell glob on name."""
    from fnmatch import fnmatchcase
    picked: dict[int, dict] = {}
    for p in patterns:
        for d in droplets:
            if str(d.get("id")) == p or d.get("name") == p or fnmatchcase(d.get("name", ""), p):
                picked[d["id"]] = d
    return list(picked.values())
