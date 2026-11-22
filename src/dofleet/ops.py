"""Operations shared by the CLI and the interactive menu. They return data; rendering lives in cli.py."""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, field

from . import cloudinit, fleet, placement, volumes
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
    volumes: list[int] = field(default_factory=list)


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
    upload_key: tuple[str, str] | None = None   # (local .pub path, public key) to add to the account first


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


def local_public_key(settings: Settings) -> tuple[str, str] | None:
    """First readable public key from defaults.local_keys, for accounts that have no SSH key yet."""
    if str(settings.defaults.get("upload_local_key", "yes")).lower() in ("no", "false", "0"):
        return None
    for raw in settings.defaults.get("local_keys", []):
        path = os.path.expanduser(raw)
        try:
            text = open(path, encoding="utf-8").read().strip()
        except OSError:
            continue
        if text.startswith(("ssh-", "ecdsa-", "sk-")):
            return path, text
    return None


def local_identity(settings: Settings) -> str | None:
    """Private key next to the first local public key that exists (for ssh -i)."""
    for raw in settings.defaults.get("local_keys", []):
        path = os.path.expanduser(raw)
        if path.endswith(".pub") and os.path.isfile(path) and os.path.isfile(path[:-4]):
            return path[:-4]
    return None


def plan_up(client: DOClient, settings: Settings, preset_name: str, prefix: str | None, count: int,
            ov: Overrides) -> Plan:
    preset = settings.preset(preset_name)
    if ov.volumes:
        preset["volumes"] = ov.volumes
    volumes.sizes_gb(preset)  # validate before any network call
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
    wanted_keys = settings.defaults.get("ssh_keys", "all")
    key_ids = resolve_ssh_keys(client, wanted_keys)
    upload = local_public_key(settings) if not key_ids and wanted_keys == "all" else None
    has_key = bool(key_ids or upload)
    tmpl_vars = {**preset.get("vars", {}), **ov.vars}
    # Without any key DigitalOcean emails a root password: keep password + root login on, or the box is unreachable.
    tmpl_vars.setdefault("password_auth", "no" if has_key else "yes")
    tmpl_vars.setdefault("root_login", "prohibit-password" if has_key else "yes")
    user_data, generated = cloudinit.render(preset.get("cloud_init"), tmpl_vars,
                                            mount_volumes=bool(preset.get("volumes")))
    taken = {d["name"] for d in client.droplets()}
    names = fleet.numbered_names(prefix or preset["name"], count, taken)
    tags = [fleet.MARK_TAG, fleet.PRESET_PREFIX + fleet.tag_safe(preset["name"])]
    tags += [fleet.tag_safe(t) for t in [*preset.get("tags", []), *ov.tags]]
    hourly, monthly = float(choice.size.get("price_hourly", 0)), float(choice.size.get("price_monthly", 0))
    vol_month = volumes.monthly_cost(preset, float(settings.defaults.get("volume_usd_per_gb_month", 0.10)))
    hourly, monthly = hourly + vol_month / fleet.HOURS_PER_MONTH, monthly + vol_month
    cost_ttl, cost_month = fleet.batch_cost(hourly, monthly, count, ttl_s)
    return Plan(preset, choice.region, choice.size, choice.fell_back, names, ov.image or preset["image"], key_ids,
                ttl_s, tags, user_data, generated, cost_ttl, cost_month, regions, sizes, upload)


def ensure_key(client: DOClient, public_key: str) -> int:
    body = " ".join(public_key.split()[:2])
    for k in client.ssh_keys():
        if " ".join((k.get("public_key") or "").split()[:2]) == body:
            return k["id"]
    # Named after the key itself, not the machine: a hostname can carry an IP or a client name.
    name = f"dofleet-{hashlib.sha256(body.encode()).hexdigest()[:10]}"
    return client.create_ssh_key(name, public_key)["id"]


def _sold_out(err: ApiError) -> bool:
    return err.status == 422 and any(h in err.message.lower() for h in SOLD_OUT_HINTS)


def execute_up(client: DOClient, settings: Settings, plan: Plan, now: float | None = None) -> list[dict]:
    """Create in chunks of max_per_batch. When the API says a size is gone between planning and creating,
    move to the next pair in the chain and keep going."""
    vol_sizes = volumes.sizes_gb(plan.preset)
    # Volumes attach to exactly one droplet, so a preset with volumes creates one droplet per call.
    chunk = 1 if vol_sizes else max(1, min(10, int(settings.defaults.get("max_per_batch", 10))))
    if plan.upload_key:
        plan.ssh_key_ids.append(ensure_key(client, plan.upload_key[1]))
        plan.upload_key = None
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
        vol_ids = volumes.create_for(client, batch[0], plan.region, vol_sizes) if vol_sizes else []
        if vol_ids:
            body["volumes"] = vol_ids
        try:
            created += client.create_droplets(body)
        except ApiError as e:
            volumes.cleanup(client, vol_ids)
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


def orphan_volumes(client: DOClient, now: float, min_age_s: int = 3600) -> list[dict]:
    """dofleet volumes attached to nothing for longer than min_age_s: left behind and still billing."""
    return [v for v in client.volumes() if fleet.MARK_TAG in (v.get("tags") or []) and not v.get("droplet_ids")
            and now - fleet.created_ts(v) > min_age_s]


def cost_summary(client: DOClient, now: float) -> dict:
    bal = client.balance()
    ds = client.droplets()
    orphans = orphan_volumes(client, now)
    return {
        "month_to_date_usage": float(bal.get("month_to_date_usage") or 0),
        "month_to_date_balance": float(bal.get("month_to_date_balance") or 0),
        "account_balance": float(bal.get("account_balance") or 0),
        "droplets": len(ds),
        "fleet_monthly": round(sum(fleet.prices(d)[1] for d in ds), 2),
        "fleet_hourly": round(sum(fleet.prices(d)[0] for d in ds), 5),
        "without_timer": sum(1 for d in ds if fleet.expires_at(d) is None),
        "orphan_volumes": [v["name"] for v in orphans],
        "orphan_volume_gb": sum(int(v.get("size_gigabytes") or 0) for v in orphans),
    }
