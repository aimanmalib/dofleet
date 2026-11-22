"""Monthly spend ceiling. `budget_usd` in [defaults] (0 = off).

Two guards, both based on DigitalOcean's own month-to-date usage figure:
- before creating: refuse when usage so far + what the new batch would cost until its timer (or a full month without one)
  would pass the budget;
- in `reap`: once usage so far has passed the budget, `budget_action = "reap"` deletes every dofleet droplet
  (with its volumes); "warn" only reports."""

from __future__ import annotations

from dataclasses import dataclass

from .api import DOClient
from .config import ConfigError, Settings


@dataclass
class Status:
    budget: float
    used: float
    committed: float = 0.0   # what running droplets will still cost until their timers (or month end)

    @property
    def on(self) -> bool:
        return self.budget > 0

    @property
    def over(self) -> bool:
        return self.on and self.used >= self.budget

    @property
    def left(self) -> float:
        return max(0.0, self.budget - self.used - self.committed)


def committed(droplets: list[dict], now: float) -> float:
    """Remaining cost of running droplets: until their expiry timer, or until month end without one."""
    import calendar
    from datetime import datetime, timezone
    from . import fleet
    d = datetime.fromtimestamp(now, timezone.utc)
    month_end = datetime(d.year, d.month, calendar.monthrange(d.year, d.month)[1], 23, 59, tzinfo=timezone.utc).timestamp()
    total = 0.0
    for x in droplets:
        hourly, monthly = fleet.prices(x)
        until = min(fleet.expires_at(x) or month_end, month_end)
        hours_left = max(0.0, until - now) / 3600
        already = max(0.0, now - fleet.created_ts(x)) / 3600 * hourly
        total += max(0.0, min(hours_left * hourly, (monthly or 1e12) - already))
    return total


def status(client: DOClient, settings: Settings, now: float | None = None) -> Status:
    import time
    budget = float(settings.defaults.get("budget_usd") or 0)
    if budget <= 0:
        return Status(0.0, 0.0)
    return Status(budget, float(client.balance().get("month_to_date_usage") or 0),
                  committed(client.droplets(), now or time.time()))


def check_new(st: Status, extra_cost: float) -> None:
    if st.on and st.used + st.committed + extra_cost > st.budget:
        raise ConfigError("err.budget", used=_usd(st.used + st.committed), extra=_usd(extra_cost), budget=_usd(st.budget))


def _usd(x: float) -> str:
    return f"{x:.2f}" if x >= 0.01 or x == 0 else f"{x:.4f}"


def action(settings: Settings) -> str:
    a = str(settings.defaults.get("budget_action") or "reap").lower()
    return a if a in ("reap", "warn") else "reap"
