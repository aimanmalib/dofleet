"""Wait until new droplets are active, have a public IP, and answer on a TCP port."""

from __future__ import annotations

import socket
import time
from typing import Callable

from .api import DOClient, public_ipv4


def port_open(ip: str, port: int, timeout: float = 5.0) -> bool:
    try:
        with socket.create_connection((ip, port), timeout=timeout):
            return True
    except OSError:
        return False


def wait_ready(client: DOClient, ids: list[int], port: int, timeout_s: int, *,
               on_update: Callable[[dict[int, str]], None] = lambda s: None,
               probe: Callable[[str, int], bool] | None = None,
               sleep: Callable[[float], None] = time.sleep,
               clock: Callable[[], float] = time.monotonic,
               interval: float = 5.0) -> dict[int, dict]:
    """Returns id -> {"droplet": dict, "ip": str|None, "state": "ready"|"active"|"new"|"timeout"}."""
    probe = probe or port_open  # looked up at call time so it can be replaced
    deadline = clock() + timeout_s
    result: dict[int, dict] = {i: {"droplet": {}, "ip": None, "state": "new"} for i in ids}
    while True:
        for i, r in result.items():
            if r["state"] == "ready":
                continue
            if r["state"] == "new":
                d = client.droplet(i)
                r["droplet"] = d
                r["ip"] = public_ipv4(d)
                if d.get("status") == "active" and r["ip"]:
                    r["state"] = "active"
            if r["state"] == "active" and probe(r["ip"], port):
                r["state"] = "ready"
        on_update({i: r["state"] for i, r in result.items()})
        if all(r["state"] == "ready" for r in result.values()):
            return result
        if clock() >= deadline:
            for r in result.values():
                if r["state"] != "ready":
                    r["state"] = "timeout"
            return result
        sleep(interval)
