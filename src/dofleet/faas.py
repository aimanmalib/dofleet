"""Install the reaper as a scheduled DigitalOcean Function, so nothing has to run on your own machine.

One Functions namespace labelled `dofleet` holds one action (`dofleet-reap`) and one scheduled trigger. The namespace key
is only returned when the namespace is created, so (re)installing deletes the old namespace and makes a new one; that
keeps install idempotent. The DigitalOcean token is stored as an action parameter inside your own Functions namespace."""

from __future__ import annotations

from importlib import resources

import httpx

from .api import DOClient
from .config import ConfigError

LABEL = "dofleet"
ACTION = "dofleet-reap"
TRIGGER = "dofleet-reap-schedule"


def namespaces(client: DOClient) -> list[dict]:
    return [n for n in (client.request("GET", "/functions/namespaces").get("namespaces") or []) if n.get("label") == LABEL]


def uninstall(client: DOClient) -> int:
    found = namespaces(client)
    for n in found:
        client.request("DELETE", f"/functions/namespaces/{n['namespace']}")
    return len(found)


def _python_kind(http: httpx.Client, host: str) -> str:
    kinds = http.get(f"{host}/api/v1").json().get("runtimes", {}).get("python", [])
    if not kinds:
        raise ConfigError("err.faas_runtime")
    default = [k["kind"] for k in kinds if k.get("default")]
    return default[0] if default else kinds[-1]["kind"]


def install(client: DOClient, token: str, *, region: str, cron: str, grace_s: int, budget_usd: float,
            budget_action: str, notify_url: str = "", http: httpx.Client | None = None) -> dict:
    uninstall(client)
    ns = client.request("POST", "/functions/namespaces", json={"region": region, "label": LABEL})["namespace"]
    host, name, auth = ns["api_host"], ns["namespace"], (ns["uuid"], ns["key"])
    http = http or httpx.Client(timeout=60)
    code = resources.files("dofleet").joinpath("data", "reaper_function.py").read_text(encoding="utf-8")
    params = [{"key": "token", "value": token}, {"key": "grace_s", "value": grace_s},
              {"key": "budget_usd", "value": budget_usd}, {"key": "budget_action", "value": budget_action},
              {"key": "notify_url", "value": notify_url}]
    r = http.put(f"{host}/api/v1/namespaces/{name}/actions/{ACTION}", params={"overwrite": "true"}, auth=auth,
                 json={"exec": {"kind": _python_kind(http, host), "code": code}, "parameters": params,
                       "limits": {"timeout": 120000, "memory": 256}})
    if r.status_code >= 300:
        raise ConfigError("err.faas_deploy", status=r.status_code, msg=r.text[:200])
    client.request("POST", f"/functions/namespaces/{name}/triggers", json={
        "name": TRIGGER, "function": ACTION, "type": "SCHEDULED", "is_enabled": True,
        "scheduled_details": {"cron": cron, "body": {}}})
    # Run once now with dry_run so the user sees it can reach the API with this token.
    r = http.post(f"{host}/api/v1/namespaces/{name}/actions/{ACTION}", params={"blocking": "true", "result": "true"},
                  auth=auth, json={"dry_run": True})
    body = r.json().get("body", r.json()) if r.status_code == 200 else {"error": r.text[:200]}
    return {"namespace": name, "region": region, "cron": cron, "test_run": body}
