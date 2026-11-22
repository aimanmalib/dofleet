"""Install the reaper as a scheduled DigitalOcean Function, so nothing has to run on your own machine.

One Functions namespace labelled `dofleet` holds one action (`dofleet-reap`) and one scheduled trigger. The namespace key
is only returned when the namespace is created, so (re)installing makes a new namespace, and only once that one is
deployed and scheduled are the old ones deleted: a failed reinstall never leaves you without a reaper. The DigitalOcean token is stored as an action parameter inside your own Functions namespace."""

from __future__ import annotations

import time
from importlib import resources

import httpx

from .api import DOClient
from .config import ConfigError

LABEL = "dofleet"
ACTION = "dofleet-reap"
TRIGGER = "dofleet-reap-schedule"


def _ours(label: str) -> bool:
    rest = label[len(LABEL):]
    return label == LABEL or (label.startswith(LABEL + "-") and rest[1:].isdigit())


def namespaces(client: DOClient) -> list[dict]:
    return [n for n in (client.request("GET", "/functions/namespaces").get("namespaces") or []) if _ours(n.get("label", ""))]


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


def every_to_cron(seconds: int) -> str:
    """5m..59m -> */m minutes; 1h..23h -> every h hours; 1d -> daily. Anything else has no clean cron form."""
    if seconds % 60 == 0 and 60 <= seconds < 3600 and 60 % (seconds // 60) == 0:
        return f"*/{seconds // 60} * * * *"
    if seconds % 3600 == 0 and 3600 <= seconds < 86400 and 24 % (seconds // 3600) == 0:
        return f"0 */{seconds // 3600} * * *"
    if seconds == 86400:
        return "0 0 * * *"
    raise ConfigError("err.faas_every")


def install(client: DOClient, token: str, *, region: str, cron: str, grace_s: int, budget_usd: float,
            budget_action: str, notify_url: str = "", http: httpx.Client | None = None) -> dict:
    old = namespaces(client)
    # labels must be unique per account, and the old reaper stays until the new one works: so a timestamped label
    label = f"{LABEL}-{int(time.time())}"
    ns = client.request("POST", "/functions/namespaces", json={"region": region, "label": label})["namespace"]
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
    for n in old:  # the new reaper is live; only now remove the previous one
        client.request("DELETE", f"/functions/namespaces/{n['namespace']}")
    return {"namespace": name, "region": region, "cron": cron, "test_run": body}
