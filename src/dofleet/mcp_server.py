"""`dofleet mcp`: an MCP server (stdio) that lets an AI agent borrow droplets without holding your token.

Every request goes through the policy in [mcp] of config.toml, enforced here and not by the agent:
- presets: which presets the agent may use; max_ttl: longest timer it may set or extend to; max_droplets: how many
  dofleet droplets may exist at once; the month budget (`budget_usd`) applies as for the CLI.
- the agent can only see, run commands on, extend or delete droplets it created itself (tag `dofleet-mcp`);
  droplets a person made with `dofleet up` are invisible to it. `scope = "all"` widens that to every dofleet droplet.
Speaks newline-delimited JSON-RPC 2.0 (MCP stdio transport); no SDK needed."""

from __future__ import annotations

import json
import subprocess
import sys
import time

from . import __version__, budget, fleet, launch, ops, ready, volumes
from .api import ApiError, DOClient
from .config import ConfigError, Settings
from .i18n import t

OUTPUT_LIMIT = 20_000
AGENT_TAG = "dofleet-mcp"
DEFAULT_POLICY = {"presets": ["tiny", "quick", "docker", "scratch"], "max_ttl": "4h", "max_droplets": 3,
                  "exec_timeout_s": 600, "scope": "own"}

TOOLS = [
    {"name": "dofleet_list", "description": "List the dofleet droplets: name, IP, status, spend so far, time left.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "dofleet_create", "description": "Create one droplet from an allowed preset. Always has an expiry timer.",
     "inputSchema": {"type": "object", "properties": {
         "preset": {"type": "string"}, "name": {"type": "string"},
         "ttl": {"type": "string", "description": "e.g. 30m, 2h (capped by policy)"}}, "required": ["preset"]}},
    {"name": "dofleet_exec", "description": "Run a shell command on a dofleet droplet over SSH; returns exit code and output.",
     "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "command": {"type": "string"},
                                                      "timeout_s": {"type": "integer"}}, "required": ["name", "command"]}},
    {"name": "dofleet_extend", "description": "Set a droplet's timer to expire this long from now (capped by policy).",
     "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}, "ttl": {"type": "string"}},
                     "required": ["name", "ttl"]}},
    {"name": "dofleet_delete", "description": "Delete a dofleet droplet and its dofleet volumes.",
     "inputSchema": {"type": "object", "properties": {"name": {"type": "string"}}, "required": ["name"]}},
    {"name": "dofleet_cost", "description": "Month-to-date usage, budget left, and what running droplets cost.",
     "inputSchema": {"type": "object", "properties": {}}},
]


class Refused(Exception):
    pass


class MissingToken:
    """Stands in for the API client when no token is set. The server still starts and lists its tools (MCP clients and
    directories inspect it that way); every tool call then answers with the same "no token" error the CLI prints."""

    def __init__(self, error: ConfigError):
        self.error = error

    def __getattr__(self, name):
        raise self.error


class Server:
    def __init__(self, client: DOClient, settings: Settings, *, run=subprocess.run, now=time.time):
        self.client, self.settings, self.run, self.now = client, settings, run, now
        self.policy = {**DEFAULT_POLICY, **(settings.data.get("mcp") or {})}
        self.max_ttl = fleet.parse_duration(self.policy["max_ttl"])
        self.scope_tag = fleet.MARK_TAG if self.policy.get("scope") == "all" else AGENT_TAG

    def tools(self) -> list[dict]:
        """TOOLS with this policy written into the argument descriptions, so an agent knows its limits up front."""
        p = self.policy
        hints = {
            "dofleet_create": {"preset": f"Preset to use. Allowed: {', '.join(p['presets'])}.",
                               "name": "Name prefix for the droplet (optional).",
                               "ttl": f"Timer, e.g. 30m or 2h. At most {p['max_ttl']}, which is also the default."},
            "dofleet_exec": {"name": "A droplet you created (see dofleet_list).",
                             "command": "Shell command, run as the preset's login user.",
                             "timeout_s": f"Seconds to wait, at most {p['exec_timeout_s']}."},
            "dofleet_extend": {"name": "A droplet you created.",
                               "ttl": f"New timer counted from now, e.g. 1h. At most {p['max_ttl']}."},
            "dofleet_delete": {"name": "A droplet you created."},
        }
        out = json.loads(json.dumps(TOOLS))
        for tool in out:
            for arg, schema in tool["inputSchema"]["properties"].items():
                if arg in hints.get(tool["name"], {}):
                    schema["description"] = hints[tool["name"]][arg]
        return out

    def _visible(self) -> list[dict]:
        return [d for d in self.client.droplets(self.scope_tag) if fleet.is_managed(d)]

    # ---- policy helpers ---------------------------------------------------
    def _ttl(self, text: str | None) -> int:
        ttl = fleet.parse_duration(text) if text else self.max_ttl
        if ttl > self.max_ttl:
            raise Refused(t("mcp.ttl_cap", ttl=text, max=self.policy["max_ttl"]))
        return ttl

    def _mine(self, name: str) -> dict:
        hits = [d for d in self._visible() if d.get("name") == name or str(d.get("id")) == name]
        if not hits:
            raise Refused(t("mcp.not_found", name=name))
        return hits[0]

    # ---- tools ------------------------------------------------------------
    def dofleet_list(self, _):
        return ops.rows(self._visible(), self.now())

    def dofleet_cost(self, _):
        c = ops.cost_summary(self.client, self.now())
        budget = float(self.settings.defaults.get("budget_usd") or 0)
        return {**c, "budget_usd": budget or None,
                "budget_left_usd": round(max(0.0, budget - c["month_to_date_usage"]), 2) if budget else None}

    def dofleet_create(self, args):
        preset = args.get("preset", "")
        if preset not in self.policy["presets"]:
            raise Refused(t("mcp.preset_denied", preset=preset, allowed=", ".join(self.policy["presets"])))
        if len(self._visible()) >= int(self.policy["max_droplets"]):
            raise Refused(t("mcp.too_many", max=self.policy["max_droplets"]))
        ttl = self._ttl(args.get("ttl"))
        plan = ops.plan_up(self.client, self.settings, preset, args.get("name") or "agent", 1,
                           ops.Overrides(ttl=f"{max(1, ttl // 60)}m", tags=[AGENT_TAG]))
        res = launch.create_and_wait(self.client, self.settings, plan)
        return [{"name": r["droplet"].get("name"), "ip": r["ip"], "state": r["state"],
                 "login_user": launch.login_user(self.settings, r["droplet"]),
                 "expires_in": fleet.format_duration(ttl), "cost_until_expiry_usd": round(plan.cost_ttl, 3)}
                for r in res.values()]

    def dofleet_exec(self, args):
        d = self._mine(args["name"])
        ip = ops.rows([d], self.now())[0]["ip"]
        if not ip:
            raise Refused(t("err.no_ip"))
        timeout = min(int(args.get("timeout_s") or self.policy["exec_timeout_s"]), int(self.policy["exec_timeout_s"]))
        cmd = ["ssh", *ready.ssh_args(d["id"], ops.local_identity(self.settings)),
               f"{launch.login_user(self.settings, d)}@{ip}", args["command"]]
        try:
            p = self.run(cmd, capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"exit_code": None, "timed_out": True}
        return {"exit_code": p.returncode, "stdout": p.stdout[-OUTPUT_LIMIT:], "stderr": p.stderr[-OUTPUT_LIMIT:]}

    def dofleet_extend(self, args):
        d = self._mine(args["name"])
        ttl = self._ttl(args["ttl"])
        hourly, _ = fleet.prices(d)
        budget.check_new(budget.status(self.client, self.settings, self.now()), hourly * ttl / 3600)
        ops.set_expiry(self.client, d, ttl, self.now(), from_now=True)
        return {"name": d["name"], "expires_in": fleet.format_duration(ttl)}

    def dofleet_delete(self, args):
        d = self._mine(args["name"])
        vols = volumes.destroy(self.client, d)
        return {"deleted": d["name"], "volumes": vols}

    # ---- protocol ---------------------------------------------------------
    def handle(self, msg: dict) -> dict | None:
        method, mid = msg.get("method"), msg.get("id")
        if mid is None:
            return None  # notification
        if method == "initialize":
            ver = (msg.get("params") or {}).get("protocolVersion") or "2025-06-18"
            result = {"protocolVersion": ver, "capabilities": {"tools": {}},
                      "serverInfo": {"name": "dofleet", "version": __version__}}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": self.tools()}
        elif method == "tools/call":
            params = msg.get("params") or {}
            result = self.call(params.get("name", ""), params.get("arguments") or {})
        else:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"unknown method {method}"}}
        return {"jsonrpc": "2.0", "id": mid, "result": result}

    def call(self, name: str, args: dict) -> dict:
        fn = getattr(self, name, None) if name in {x["name"] for x in TOOLS} else None
        if fn is None:
            return {"content": [{"type": "text", "text": f"unknown tool {name}"}], "isError": True}
        try:
            data = fn(args)
            return {"content": [{"type": "text", "text": json.dumps(data, default=str)}], "isError": False}
        except (Refused, ConfigError, ApiError, ValueError) as e:
            text = t(e.key, **e.kw) if isinstance(e, ConfigError) else str(e)
            return {"content": [{"type": "text", "text": text}], "isError": True}
        except Exception as e:  # noqa: BLE001 - one bad call (missing argument, network) must not end the server
            return {"content": [{"type": "text", "text": f"{type(e).__name__}: {e}"}], "isError": True}


def serve(client: DOClient, settings: Settings, stdin=sys.stdin, stdout=sys.stdout) -> None:
    server = Server(client, settings)
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            reply = server.handle(json.loads(line))
        except json.JSONDecodeError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "parse error"}}
        if reply is not None:
            stdout.write(json.dumps(reply) + "\n")
            stdout.flush()
