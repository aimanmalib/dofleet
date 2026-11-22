"""Wait until new droplets are active, have a public IP, and answer on a TCP port."""

from __future__ import annotations

import shutil
import socket
import subprocess
import time
from typing import Callable

from .api import DOClient, public_ipv4


def port_open(ip: str, port: int, timeout: float = 5.0) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


SSH_OPTS = ["-o", "BatchMode=yes", "-o", "StrictHostKeyChecking=accept-new", "-o", "ConnectTimeout=8",
            "-o", "LogLevel=ERROR"]


def cloud_init_state(ip: str, identity: str | None = None) -> str:
    """'done' | 'running' | 'failed' | 'unknown' (no ssh, no key that works, or no cloud-init)."""
    if not shutil.which("ssh"):
        return "unknown"
    try:
        ident = ["-i", identity, "-o", "IdentitiesOnly=yes"] if identity else []
        res = subprocess.run(["ssh", *SSH_OPTS, *ident, f"root@{ip}", "cloud-init status"],
                             capture_output=True, text=True, timeout=30)
    except (subprocess.TimeoutExpired, OSError):
        return "running"
    if res.returncode == 255:  # ssh itself failed: auth or network
        return "unknown" if "denied" in res.stderr.lower() else "running"
    status = next((line.split(":", 1)[1].strip() for line in res.stdout.splitlines()
                   if line.startswith("status:")), "")
    if status in ("done", "disabled"):
        return "done"
    if status in ("running", "not started", "not run"):
        return "running"
    return "failed" if status in ("error", "degraded done") or res.returncode == 1 else "unknown"


def wait_ready(client: DOClient, ids: list[int], port: int, timeout_s: int, *,
               on_update: Callable[[dict[int, str]], None] = lambda s: None,
               probe: Callable[[str, int], bool] | None = None,
               sleep: Callable[[float], None] = time.sleep,
               clock: Callable[[], float] = time.monotonic,
               interval: float = 5.0,
               setup: Callable[[str], str] | None = None) -> dict[int, dict]:
    """Returns id -> {"droplet", "ip", "state"}; state is ready | setup_failed | port_open | active | new | timeout.
    With `setup`, a droplet whose port answers is only "ready" once cloud-init reports done (or cannot be asked)."""
    probe = probe or port_open  # looked up at call time so it can be replaced
    final = ("ready", "setup_failed")
    deadline = clock() + timeout_s
    result: dict[int, dict] = {i: {"droplet": {}, "ip": None, "state": "new"} for i in ids}
    while True:
        for i, r in result.items():
            if r["state"] in final:
                continue
            if r["state"] == "new":
                d = client.droplet(i)
                r["droplet"] = d
                r["ip"] = public_ipv4(d)
                if d.get("status") == "active" and r["ip"]:
                    r["state"] = "active"
            if r["state"] == "active" and probe(r["ip"], port):
                r["state"] = "port_open" if setup else "ready"
            if r["state"] == "port_open":
                st = setup(r["ip"])
                if st in ("done", "unknown"):
                    r["state"], r["setup"] = "ready", st
                elif st == "failed":
                    r["state"] = "setup_failed"
        on_update({i: r["state"] for i, r in result.items()})
        if all(r["state"] in final for r in result.values()):
            return result
        if clock() >= deadline:
            for r in result.values():
                if r["state"] not in final:
                    r["state"] = "timeout"
            return result
        sleep(interval)
