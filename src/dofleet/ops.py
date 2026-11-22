"""Operations shared by the CLI and the interactive menu. They return data; rendering lives in cli.py."""

from __future__ import annotations

import time
from dataclasses import dataclass, field

from . import cloudinit, fleet, placement
from .api import ApiError, DOClient, public_ipv4
from .config import ConfigError, Settings

SOLD_OUT_HINTS = ("not available", "sold out", "capacity", "unavailable")


@dataclass
class Overrides:
    regions: list[str] = field(default_factory=list)
    sizes: list[str] = field(default_factory=list)
    image: str | None = None
    ttl: str | None = None          # "" = no timer
    tags: list[str] = field(default_factory=list)
    vars: dict[str, str] = field(default_factory=dict)


@dataclass
class Plan:
    preset: dict
    region: str
    size: dict
    fell_back: bool
    names: list[str]
    image: str
    ssh_key_ids: list[int]
    ttl_s: int | None
    tags: list[str]
    user_data: str | None
    generated: dict[str, str]
    cost_ttl: float
    cost_month: float
    regions_tried: list[str]
    sizes_tried: list[str]


def resolve_ssh_keys(client: DOClient, wanted) -> list[int]:
    if wanted in (None, "none", []):
        return []
    keys = client.ssh_keys()
    if wanted == "all":
        return [k["id"] for k in keys]
    wanted = [wanted] if isinstance(wanted, str) else list(wanted)
    out = []
    for w in wanted:
        hit = [k["id"] for k in keys if w in (k.get("name"), k.get("fingerprint"), str(k.get("id")))]
        if not hit:
            raise ConfigError("err.no_ssh_key", name=w)
        out += hit
    return out


def plan_up(client: DOClient, settings: Settings, preset_name: str, prefix: str | None, count: int,
            ov: Overrides) -> Plan:
    preset = settings.preset(preset_name)
    limit = int(settings.defaults.get("max_per_batch", 10))
    if count < 1 or count > limit * 10:
        raise ConfigError("err.bad_count", max=limit * 10)
    ttl_text = preset.get("ttl", "") if ov.ttl is None else ov.ttl
    ttl_s = fleet.parse_duration(ttl_text) if ttl_text else None  # validate before any network call
    regions = ov.regions or preset["regions"]
    sizes = ov.sizes or preset["sizes"]
    all_sizes, all_regions = client.sizes(), client.regions()
    choice = placement.choose(regions, sizes, all_sizes, all_regions)
    if choice is None:
        raise ConfigError("err.sold_out", regions=", ".join(regions), sizes=", ".join(sizes))
    key_ids = resolve_ssh_keys(client, settings.defaults.get("ssh_keys", "all"))
    tmpl_vars = {**preset.get("vars", {}), **ov.vars}
    tmpl_vars.setdefault("password_auth", "no" if key_ids else "yes")
    user_data, generated = cloudinit.render(preset.get("cloud_init"), tmpl_vars)
    taken = {d["name"] for d in client.droplets()}
    names = fleet.numbered_names(prefix or preset["name"], count, taken)
    tags = [fleet.MARK_TAG, fleet.PRESET_PREFIX + fleet.tag_safe(preset["name"])]
    tags += [fleet.tag_safe(t) for t in [*preset.get("tags", []), *ov.tags]]
    hourly, monthly = float(choice.size.get("price_hourly", 0)), float(choice.size.get("price_monthly", 0))
    cost_ttl, cost_month = fleet.batch_cost(hourly, monthly, count, ttl_s)
    return Plan(preset, choice.region, choice.size, choice.fell_back, names, ov.image or preset["image"], key_ids,
                ttl_s, tags, user_data, generated, cost_ttl, cost_month, regions, sizes)


def _sold_out(err: ApiError) -> bool:
    return err.status == 422 and any(h in err.message.lower() for h in SOLD_OUT_HINTS)


def execute_up(client: DOClient, settings: Settings, plan: Plan, now: float | None = None) -> list[dict]:
    """Create in chunks of max_per_batch. When the API says a size is gone between planning and creating,
    move to the next pair in the chain and keep going."""
    chunk = max(1, min(10, int(settings.defaults.get("max_per_batch", 10))))
    created: list[dict] = []
    skip: set[tuple[str, str]] = set()
    pending = list(plan.names)
    while pending:
        batch, rest = pending[:chunk], pending[chunk:]
        tags = list(plan.tags)
        if plan.ttl_s:
            tags.append(fleet.expiry_tag(now if now is not None else time.time(), plan.ttl_s))
        body = {"names": batch, "region": plan.region, "size": plan.size["slug"], "image": plan.image,
                "ssh_keys": plan.ssh_key_ids, "tags": tags, "monitoring": bool(plan.preset.get("monitoring")),
                "ipv6": bool(plan.preset.get("ipv6"))}
        if plan.user_data:
            body["user_data"] = plan.user_data
        try:
            created += client.create_droplets(body)
        except ApiError as e:
            if not _sold_out(e):
                raise
            skip.add((plan.region, plan.size["slug"]))
            nxt = placement.choose(plan.regions_tried, plan.sizes_tried, client.sizes(), client.regions(), skip)
            if nxt is None:
                raise ConfigError("err.sold_out", regions=", ".join(plan.regions_tried),
                                  sizes=", ".join(plan.sizes_tried)) from e
            plan.region, plan.size, plan.fell_back = nxt.region, nxt.size, True
            continue
        pending = rest
    return created


def rows(droplets: list[dict], now: float) -> list[dict]:
    out = []
    for d in droplets:
        hourly, monthly = fleet.prices(d)
        exp = fleet.expires_at(d)
        out.append({
            "id": d["id"], "name": d.get("name"), "ip": public_ipv4(d), "status": d.get("status"),
            "region": (d.get("region") or {}).get("slug"), "size": d.get("size_slug"),
            "age_s": int(now - fleet.created_ts(d)), "spent_usd": round(fleet.accrued(d, now), 2),
            "monthly_usd": monthly, "hourly_usd": hourly, "managed": fleet.is_managed(d),
            "expires_at": exp, "expires_in_s": (exp - int(now)) if exp else None,
        })
    return sorted(out, key=lambda r: (r["expires_in_s"] is None, r["expires_in_s"] or 0, r["name"] or ""))


def reap_list(client: DOClient, settings: Settings, now: float) -> list[dict]:
    g = str(settings.defaults.get("reap_grace") or "").strip()
    grace = 0 if g in ("", "0", "0m", "0h", "0d") else fleet.parse_duration(g)
    return [d for d in fleet.expired(client.droplets(fleet.MARK_TAG), now - grace) if fleet.is_managed(d)]


def set_expiry(client: DOClient, droplet: dict, ttl_s: int | None, now: float) -> int | None:
    """ttl_s=None removes the timer. Otherwise the new expiry = later of (now, current expiry) + ttl."""
    old = [t for t in droplet.get("tags", []) if t.startswith(fleet.EXP_PREFIX)]
    new_exp = None
    if ttl_s is not None:
        base = max(now, fleet.expires_at(droplet) or now)
        new_exp = int(base + ttl_s)
        client.tag_resource(f"{fleet.EXP_PREFIX}{new_exp}", droplet["id"])
        client.tag_resource(fleet.MARK_TAG, droplet["id"])
    for t in old:
        if t != f"{fleet.EXP_PREFIX}{new_exp}":
            client.untag_resource(t, droplet["id"])
    return new_exp


def cost_summary(client: DOClient, now: float) -> dict:
    bal = client.balance()
    ds = client.droplets()
    return {
        "month_to_date_usage": float(bal.get("month_to_date_usage") or 0),
        "month_to_date_balance": float(bal.get("month_to_date_balance") or 0),
        "account_balance": float(bal.get("account_balance") or 0),
        "droplets": len(ds),
        "fleet_monthly": round(sum(fleet.prices(d)[1] for d in ds), 2),
        "fleet_hourly": round(sum(fleet.prices(d)[0] for d in ds), 5),
        "without_timer": sum(1 for d in ds if fleet.expires_at(d) is None),
    }
