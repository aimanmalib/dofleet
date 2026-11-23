"""Operations shared by the CLI and the interactive menu. They return data; rendering lives in cli.py."""

from __future__ import annotations

import hashlib
import os
import time
from dataclasses import dataclass, field

from . import bake, budget, cloudinit, fleet, placement, volumes
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
    baked: bool = False


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
    budget_left: float | None = None


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


def upload_mode(settings: Settings) -> str:
    """yes = add the local key only when the account has none; always = add it every time (CI runners); no = never."""
    mode = str(os.environ.get("DOFLEET_UPLOAD_KEY") or settings.defaults.get("upload_local_key", "yes")).lower()
    return {"false": "no", "0": "no", "true": "yes", "1": "yes"}.get(mode, mode if mode in ("yes", "no", "always") else "yes")


def local_public_key(settings: Settings) -> tuple[str, str] | None:
    """First readable public key from defaults.local_keys, for accounts that have no SSH key yet."""
    if upload_mode(settings) == "no":
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
        known = {x["slug"] for x in all_sizes}
        if not any(x in known for x in sizes):
            raise ConfigError("err.size_unknown", sizes=", ".join(sizes))
        raise ConfigError("err.sold_out", regions=", ".join(regions), sizes=", ".join(sizes))
    wanted_keys = settings.defaults.get("ssh_keys", "all")
    prefixes = tuple(settings.defaults.get("require_ttl_for") or [])
    if ttl_s is None and prefixes and choice.size["slug"].startswith(prefixes):
        raise ConfigError("err.ttl_required", size=choice.size["slug"])
    key_ids = resolve_ssh_keys(client, wanted_keys)
    mode = upload_mode(settings)
    upload = (local_public_key(settings)
              if (mode == "always" or (not key_ids and wanted_keys == "all")) and mode != "no" else None)
    has_key = bool(key_ids or upload)
    tmpl_vars = {**preset.get("vars", {}), **ov.vars}
    # Without any key DigitalOcean emails a root password: keep password + root login on, or the box is unreachable.
    tmpl_vars.setdefault("password_auth", "no" if has_key else "yes")
    tmpl_vars.setdefault("root_login", "prohibit-password" if has_key else "yes")
    image = ov.image or preset["image"]
    if ov.baked:
        image = bake.latest_image(client, preset["name"], choice.region)
        preset = {**preset, "cloud_init": None}  # the snapshot already ran the setup
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
    st = budget.status(client, settings)
    budget.check_new(st, cost_ttl)
    return Plan(preset, choice.region, choice.size, choice.fell_back, names, image, key_ids,
                ttl_s, tags, user_data, generated, cost_ttl, cost_month, regions, sizes, upload,
                st.left if st.on else None)


def key_fingerprint(public_key: str) -> str:
    """MD5 fingerprint in DigitalOcean's aa:bb:.. form."""
    import base64
    raw = base64.b64decode(public_key.split()[1])
    digest = hashlib.md5(raw, usedforsecurity=False).hexdigest()
    return ":".join(digest[i:i + 2] for i in range(0, 32, 2))


def ensure_key(client: DOClient, public_key: str) -> int:
    """Id of this public key on the account, adding it when missing. Looks the key up by fingerprint, because the
    key list lags behind right after an upload (measured: a second run seconds later got 422 'already in use')."""
    fp = key_fingerprint(public_key)
    try:
        return client.request("GET", f"/account/keys/{fp}")["ssh_key"]["id"]
    except ApiError as e:
        if e.status != 404:
            raise
    body = " ".join(public_key.split()[:2])
    name = f"dofleet-{hashlib.sha256(body.encode()).hexdigest()[:10]}"
    try:
        return client.create_ssh_key(name, public_key)["id"]
    except ApiError as e:
        if e.status != 422:
            raise
        return client.request("GET", f"/account/keys/{fp}")["ssh_key"]["id"]


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
            # the fallback may be dearer: check the budget again for what is left to create
            vol_month = volumes.monthly_cost(plan.preset, float(settings.defaults.get("volume_usd_per_gb_month", 0.10)))
            cost, _ = fleet.batch_cost(float(nxt.size.get("price_hourly", 0)) + vol_month / fleet.HOURS_PER_MONTH,
                                       float(nxt.size.get("price_monthly", 0)) + vol_month, len(pending), plan.ttl_s)
            budget.check_new(budget.status(client, settings), cost)
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


def reap_grace(settings: Settings) -> int:
    g = str(settings.defaults.get("reap_grace") or "").strip()
    return 0 if g in ("", "0", "0m", "0h", "0d") else fleet.parse_duration(g)


def reap_list(client: DOClient, settings: Settings, now: float) -> list[dict]:
    grace = reap_grace(settings)
    return [d for d in fleet.expired(client.droplets(fleet.MARK_TAG), now - grace) if fleet.is_managed(d)]


def still_expired(client: DOClient, droplet: dict, now: float, grace: int) -> bool:
    """Re-read just before deleting: someone may have run `extend` since the list was taken."""
    try:
        fresh = client.droplet(droplet["id"])
    except ApiError as e:
        return False  # gone already, or unreadable: do not delete blind
    exp = fleet.expires_at(fresh)
    return fleet.is_managed(fresh) and exp is not None and exp + grace <= now


def set_expiry(client: DOClient, droplet: dict, ttl_s: int | None, now: float, from_now: bool = False) -> int | None:
    """ttl_s=None removes the timer. Otherwise the new expiry = later of (now, current expiry) + ttl,
    or now + ttl with from_now (used where the total lifetime must stay capped)."""
    old = [t for t in droplet.get("tags", []) if t.startswith(fleet.EXP_PREFIX)]
    new_exp = None
    if ttl_s is not None:
        base = now if from_now else max(now, fleet.expires_at(droplet) or now)
        new_exp = int(base + ttl_s)
        client.tag_resource(f"{fleet.EXP_PREFIX}{new_exp}", droplet["id"])
    for t in old:
        if t != f"{fleet.EXP_PREFIX}{new_exp}":
            client.untag_resource(t, droplet["id"])
    return new_exp


DETACHED_PREFIX = "dofleet-detached-"


def orphan_volumes(client: DOClient, now: float, min_age_s: int = 3600, mark: bool = True) -> list[dict]:
    """dofleet volumes that have been attached to nothing for longer than min_age_s. "Since when" is a
    `dofleet-detached-<unix time>` tag set the first time a sweep sees the volume detached (volume age alone would
    delete a volume someone just moved by hand); the tag is cleared again once it is attached."""
    out = []
    for v in client.volumes():
        tags = v.get("tags") or []
        if fleet.MARK_TAG not in tags:
            continue
        seen = [int(x[len(DETACHED_PREFIX):]) for x in tags if x.startswith(DETACHED_PREFIX) and x[len(DETACHED_PREFIX):].isdigit()]
        if v.get("droplet_ids"):
            for x in tags:
                if x.startswith(DETACHED_PREFIX) and mark:
                    client.untag_resource(x, v["id"], "volume")
            continue
        if not seen:
            if mark and now - fleet.created_ts(v) > 300:  # skip volumes still being attached at create time
                client.tag_resource(f"{DETACHED_PREFIX}{int(now)}", v["id"], "volume")
            continue
        if now - min(seen) > min_age_s:
            out.append(v)
    return out


def stale_tags(client: DOClient, now: float, min_age_s: int = 3600, in_use: frozenset | set = frozenset()) -> list[str]:
    """`dofleet-exp-<time>` and `dofleet-detached-<time>` tags that nothing carries any more. Each droplet leaves one
    behind, and DigitalOcean keeps empty tags forever. Only tags whose time is at least min_age_s in the past qualify:
    new droplets and `extend` always write a future time and a sweep stamps the current time, so nothing can be adding
    one of these while it is deleted (deleting a tag would strip it from anything that still had it). A tag must also
    be empty by DigitalOcean's count and absent from `in_use` (tags seen on droplets and volumes just now)."""
    out = []
    for tag in client.tags():
        name = tag.get("name") or ""
        for prefix in (fleet.EXP_PREFIX, DETACHED_PREFIX):
            when = name[len(prefix):]
            if (name.startswith(prefix) and when.isdigit() and int(when) <= now - min_age_s
                    and (tag.get("resources") or {}).get("count") == 0 and name not in in_use):
                out.append(name)
    return out


def sweep_tags(client: DOClient, now: float) -> list[str]:
    """Delete stale dofleet tags. Housekeeping only: a token without tag scopes or a failed delete is skipped."""
    try:
        in_use = {x for d in client.droplets() for x in d.get("tags") or []}
        in_use |= {x for v in client.volumes() for x in v.get("tags") or []}
        stale = stale_tags(client, now, in_use=in_use)
    except ApiError:
        return []
    removed = []
    for name in stale:
        try:
            client.delete_tag(name)
            removed.append(name)
        except ApiError as e:
            if e.status == 404:  # the other reaper got there first
                removed.append(name)
    return removed


def cost_summary(client: DOClient, now: float) -> dict:
    bal = client.balance()
    ds = client.droplets()
    orphans = orphan_volumes(client, now)
    return {
        "month_to_date_usage": float(bal.get("month_to_date_usage") or 0),
        # DigitalOcean refreshes this figure a few times a day (measured 23 Nov 2026: 19 hours old)
        "usage_as_of": bal.get("generated_at"),
        "usage_age_h": round((now - fleet.created_ts({"created_at": bal["generated_at"]})) / 3600, 1)
        if bal.get("generated_at") else None,
        "month_to_date_balance": float(bal.get("month_to_date_balance") or 0),
        "account_balance": float(bal.get("account_balance") or 0),
        "droplets": len(ds),
        "fleet_monthly": round(sum(fleet.prices(d)[1] for d in ds), 2),
        "fleet_hourly": round(sum(fleet.prices(d)[0] for d in ds), 5),
        "without_timer": sum(1 for d in ds if fleet.expires_at(d) is None),
        "orphan_volumes": [v["name"] for v in orphans],
        "orphan_volume_gb": sum(int(v.get("size_gigabytes") or 0) for v in orphans),
    }
