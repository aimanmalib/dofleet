"""Create the planned droplets and wait for them: shared by `up`, `run` and the MCP server."""

from __future__ import annotations

from typing import Callable

from . import fleet, ops, ready
from .api import DOClient
from .config import Settings


def create_and_wait(client: DOClient, settings: Settings, plan: ops.Plan, *, wait: bool = True,
                    on_update: Callable[[dict[int, str]], None] = lambda s: None,
                    on_created: Callable[[list[dict]], None] = lambda ds: None) -> dict[int, dict]:
    """on_created runs as soon as the droplets exist, so a caller can clean up even if waiting fails."""
    created = ops.execute_up(client, settings, plan)
    on_created(created)
    if not wait:
        return {d["id"]: {"droplet": d, "ip": None, "state": "new"} for d in created}
    port = int(plan.preset.get("ready_port", 22))
    timeout = fleet.parse_duration(plan.preset.get("ready_timeout") or settings.defaults.get("ready_timeout", "10m"))
    ident = ops.local_identity(settings)
    def check_setup(ip, did):
        return ready.cloud_init_state(ip, ident, did)
    setup = check_setup if plan.user_data and settings.defaults.get("wait_for_setup", True) else None
    return ready.wait_ready(client, [d["id"] for d in created], port, timeout, setup=setup, on_update=on_update)


def login_user(settings: Settings, droplet: dict) -> str:
    """User the preset's setup created, else root."""
    from . import bake, cloudinit
    preset = settings.presets.get(bake.preset_of(droplet) or "", {})
    if preset.get("cloud_init"):
        return (preset.get("vars") or {}).get("user", cloudinit.DEFAULT_VARS["user"])
    return "root"
