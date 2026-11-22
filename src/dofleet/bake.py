"""Snapshots of a finished setup, so later boots skip the slow apt work.

`dofleet bake web-01` snapshots the droplet as `dofleet-<preset>-<unix time>` and keeps only the newest
`bake_keep` snapshots per preset (snapshots bill per GB per month). `dofleet up <preset> --baked` boots from the newest
one; the setup template is skipped because it already ran, only the volume mount step is kept."""

from __future__ import annotations

import time

from . import fleet
from .api import DOClient
from .config import ConfigError

PREFIX = "dofleet-"


def preset_of(droplet: dict) -> str | None:
    for tag in droplet.get("tags", []):
        if tag.startswith(fleet.PRESET_PREFIX):
            return tag[len(fleet.PRESET_PREFIX):]
    return None


def snapshots(client: DOClient, preset: str | None = None) -> list[dict]:
    """Newest first. preset=None -> every dofleet snapshot."""
    out = []
    for s in client.paginate("/snapshots", "snapshots", {"resource_type": "droplet"}):
        name = s.get("name", "")
        if not name.startswith(PREFIX):
            continue
        body, _, stamp = name[len(PREFIX):].rpartition("-")
        if not stamp.isdigit() or (preset is not None and body != fleet.tag_safe(preset)):
            continue
        out.append({**s, "preset": body, "stamp": int(stamp)})
    return sorted(out, key=lambda s: -s["stamp"])


def latest_image(client: DOClient, preset: str, region: str) -> int:
    for s in snapshots(client, preset):
        if region in s.get("regions", []):
            return int(s["id"])
    raise ConfigError("err.no_bake", preset=preset, region=region)


def bake(client: DOClient, droplet: dict, keep: int, *, now: float | None = None,
         sleep=None, timeout_s: int = 1800) -> dict:
    sleep = sleep or time.sleep
    preset = preset_of(droplet) or fleet.tag_safe(droplet["name"])
    name = f"{PREFIX}{fleet.tag_safe(preset)}-{int(now or time.time())}"
    action = client.request("POST", f"/droplets/{droplet['id']}/actions", json={"type": "snapshot", "name": name})["action"]
    waited = 0
    while action.get("status") == "in-progress":
        if waited >= timeout_s:
            raise ConfigError("err.bake_timeout", name=name)
        sleep(10)
        waited += 10
        action = client.request("GET", f"/actions/{action['id']}")["action"]
    if action.get("status") != "completed":
        raise ConfigError("err.bake_failed", name=name, status=action.get("status"))
    removed = []
    for old in snapshots(client, preset)[max(1, keep):]:
        client.request("DELETE", f"/snapshots/{old['id']}")
        removed.append(old["name"])
    return {"snapshot": name, "preset": preset, "removed": removed}
