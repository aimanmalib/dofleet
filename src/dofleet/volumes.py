"""Block storage volumes that live and die with a dofleet droplet.

A preset with `volumes = [100, 50]` gets one volume per size, created in the droplet's region, tagged `dofleet`, attached
at create time and formatted ext4 (DigitalOcean mounts it under /mnt/<name>). `down` and `reap` delete those volumes with
the droplet, so a forgotten 100 GB volume does not keep billing after the box is gone. Volumes without the `dofleet`
tag that someone attached by hand are left alone."""

from __future__ import annotations

from . import fleet
from .api import ApiError, DOClient
from .config import ConfigError

MAX_GB = 16384


def sizes_gb(preset: dict) -> list[int]:
    raw = preset.get("volumes") or []
    try:
        out = [int(x) for x in raw]
    except (TypeError, ValueError):
        out = [0]
    if any(not 1 <= x <= MAX_GB for x in out):
        raise ConfigError("err.bad_volumes", name=preset.get("name", "?"), max=MAX_GB)
    return out


def monthly_cost(preset: dict, usd_per_gb: float) -> float:
    return sum(sizes_gb(preset)) * usd_per_gb


def create_for(client: DOClient, droplet_name: str, region: str, sizes: list[int]) -> list[str]:
    """Create the volumes for one droplet. On any failure, delete the ones already made and re-raise."""
    made: list[str] = []
    try:
        for i, gb in enumerate(sizes, 1):
            name = fleet.sanitize_name(f"{droplet_name}-v{i}").lower()[:64]
            made.append(client.create_volume(name, region, gb, [fleet.MARK_TAG])["id"])
    except ApiError:
        cleanup(client, made)
        raise
    return made


def cleanup(client: DOClient, ids: list[str]) -> None:
    for vid in ids:
        try:
            client.delete_volume(vid)
        except ApiError:
            pass


def destroy(client: DOClient, droplet: dict, owned: set[str] | None = None) -> list[str]:
    """Delete a droplet plus the dofleet volumes attached to it. Returns the volume ids deleted."""
    attached = droplet.get("volume_ids") or []
    if attached and owned is None:
        owned = {v["id"] for v in client.volumes() if fleet.MARK_TAG in (v.get("tags") or [])}
    mine = [v for v in attached if v in (owned or set())]
    if mine:
        client.destroy_with_volumes(droplet["id"], mine)
    else:
        client.delete_droplet(droplet["id"])
    return mine
