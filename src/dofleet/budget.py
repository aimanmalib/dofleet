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

    @property
    def on(self) -> bool:
        return self.budget > 0

    @property
    def over(self) -> bool:
        return self.on and self.used >= self.budget

    @property
    def left(self) -> float:
        return max(0.0, self.budget - self.used)


def status(client: DOClient, settings: Settings) -> Status:
    budget = float(settings.defaults.get("budget_usd") or 0)
    if budget <= 0:
        return Status(0.0, 0.0)
    return Status(budget, float(client.balance().get("month_to_date_usage") or 0))


def check_new(st: Status, extra_cost: float) -> None:
    if st.on and st.used + extra_cost > st.budget:
        raise ConfigError("err.budget", used=_usd(st.used), extra=_usd(extra_cost), budget=_usd(st.budget))


def _usd(x: float) -> str:
    return f"{x:.2f}" if x >= 0.01 or x == 0 else f"{x:.4f}"


def action(settings: Settings) -> str:
    a = str(settings.defaults.get("budget_action") or "reap").lower()
    return a if a in ("reap", "warn") else "reap"
