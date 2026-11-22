"""Budget, GPU timer rule, bake, run, Functions reaper, MCP server."""

import io
import json
import subprocess
import time
from importlib import resources

import httpx
import pytest
from typer.testing import CliRunner

from dofleet import cli, cli_jobs, faas, fleet, mcp_server, ready, runjob  # noqa: F401 (cli_jobs registers commands)
from dofleet.api import DOClient
from fake_do import SIZES, FakeDO

runner = CliRunner()


@pytest.fixture
def fake(monkeypatch, tmp_path):
    fd = FakeDO()
    cfg = tmp_path / "config.toml"
    monkeypatch.setenv("DOFLEET_CONFIG", str(cfg))
    monkeypatch.setenv("DOFLEET_LANG", "en")
    monkeypatch.setenv("DIGITALOCEAN_TOKEN", "t")
    monkeypatch.setenv("HOME", str(tmp_path))
    cli.S._client = DOClient("t", transport=fd.transport(), sleep=lambda s: None)
    monkeypatch.setattr(ready, "port_open", lambda ip, port, timeout=5.0: True)
    monkeypatch.setattr(ready, "cloud_init_state", lambda ip, identity=None, droplet_id=None: "done")
    monkeypatch.setattr(ready.time, "sleep", lambda s: None)
    fd.cfg = cfg
    yield fd
    cli.S._client = None


def invoke(*args, input=None):
    return runner.invoke(cli.app, list(args), input=input)


def test_budget_blocks_create(fake):
    fake.cfg.write_text("[defaults]\nbudget_usd = 13\n")
    r = invoke("--json", "up", "tiny", "--yes", "--keep", "--no-wait")  # 12.50 used + $6 month > 13
    assert r.exit_code != 0 and fake.created_bodies == []
    assert "Over budget" in str(r.exception) or "err.budget" in str(r.exception)
    r = invoke("--json", "up", "tiny", "--yes", "--ttl", "1h", "--no-wait")  # + < $0.01 fits
    assert r.exit_code == 0, r.output


def test_reap_kills_all_when_over_budget(fake):
    fake.cfg.write_text('[defaults]\nbudget_usd = 10\nbudget_action = "reap"\n')
    fake.add("a", tags=["dofleet", f"dofleet-exp-{int(time.time()) + 9999}"])
    fake.add("b", tags=["dofleet"])
    fake.add("mine-by-hand")
    out = json.loads(invoke("--json", "reap", "--yes").stdout)
    assert len(out["deleted"]) == 2 and [d["name"] for d in fake.droplets.values()] == ["mine-by-hand"]
    fake.cfg.write_text('[defaults]\nbudget_usd = 10\nbudget_action = "warn"\n')
    fake.add("c", tags=["dofleet"])
    out = json.loads(invoke("--json", "reap", "--yes").stdout)
    assert out["deleted"] == [] and len(fake.droplets) == 2


def test_gpu_needs_timer(fake, monkeypatch):
    gpu = {"slug": "gpu-h100x1-80gb", "vcpus": 20, "memory": 245760, "disk": 720, "price_monthly": 2500.0,
           "price_hourly": 3.39, "regions": ["sgp1"], "available": True}
    SIZES.append(gpu)
    try:
        import fake_do
        fake_do.REGIONS[0]["sizes"].append(gpu["slug"])
        r = invoke("--json", "up", "tiny", "-s", "gpu-h100x1-80gb", "--keep", "--yes", "--no-wait")
        assert r.exit_code != 0 and fake.created_bodies == [] and "err.ttl_required" in str(r.exception)
        r = invoke("--json", "up", "tiny", "-s", "gpu-h100x1-80gb", "--ttl", "1h", "--yes", "--no-wait")
        assert r.exit_code == 0, r.output
    finally:
        SIZES.remove(gpu)
        fake_do.REGIONS[0]["sizes"].remove(gpu["slug"])


def test_bake_keeps_newest_and_up_baked_uses_it(fake, monkeypatch):
    from dofleet import bake as bakemod
    monkeypatch.setattr(bakemod.time, "sleep", lambda s: None)
    d = fake.add("web", tags=["dofleet", "dofleet-preset-tiny"])
    for _ in range(2):
        r = invoke("--json", "bake", "web", "--yes")
        assert r.exit_code == 0, r.output
        time.sleep(1.1)
    assert len(fake.snaps) == 1 and fake.snaps[0]["name"].startswith("dofleet-tiny-")
    r = invoke("--json", "up", "tiny", "--baked", "--yes", "--no-wait")
    body = fake.created_bodies[-1]
    assert r.exit_code == 0 and body["image"] == fake.snaps[0]["id"] and "user_data" not in body, r.output
    assert d["id"] in fake.droplets


def test_run_copies_runs_pulls_and_always_deletes(fake, monkeypatch, tmp_path):
    calls = []
    monkeypatch.setattr(runjob, "upload", lambda *a: calls.append(("up", a[-1])))
    monkeypatch.setattr(runjob, "execute", lambda did, ip, user, ident, cmd, env: calls.append(("exec", cmd, env)) or 3)
    monkeypatch.setattr(runjob, "download", lambda did, ip, user, ident, paths, dest: calls.append(("down", paths)))
    work = tmp_path / "w"
    work.mkdir()
    r = invoke("run", "tiny", "--sync", str(work), "--pull", "out.txt", "--env", "A=1", "--yes", "--", "make", "test")
    assert r.exit_code == 3, r.output  # remote exit code is passed through
    assert [c[0] for c in calls] == ["up", "exec", "down"] and calls[1][1:] == (["make", "test"], {"A": "1"})
    assert fake.droplets == {}  # deleted even though the command failed
    monkeypatch.setattr(runjob, "execute", lambda *a: 1)
    r = invoke("run", "tiny", "--keep-on-fail", "--yes", "--", "false")
    assert r.exit_code == 1 and len(fake.droplets) == 1


def test_runjob_pipes_real_tar(tmp_path, monkeypatch):
    """upload/download build real tar pipelines; swap ssh for a local shell to prove the plumbing."""
    src, remote, dest = tmp_path / "src", tmp_path / "remote", tmp_path / "dest"
    src.mkdir(), remote.mkdir()
    (src / "a.txt").write_text("hello")
    monkeypatch.setattr(runjob, "_ssh", lambda *a: ["bash", "-c", f'cd {remote} && eval "$0"'])
    runjob.upload(1, "ip", "u", None, src)
    assert (remote / "work" / "a.txt").read_text() == "hello"
    (remote / "work" / "result.txt").write_text("done")
    runjob.download(1, "ip", "u", None, ["result.txt"], dest)
    assert (dest / "result.txt").read_text() == "done"
    with pytest.raises(runjob.JobError):
        runjob.download(1, "ip", "u", None, ["missing.txt"], dest)


def test_reaper_function_logic():
    spec = resources.files("dofleet").joinpath("data", "reaper_function.py").read_text()
    mod = {}
    exec(compile(spec, "reaper_function.py", "exec"), mod)
    fd = FakeDO()
    old = fd.add("old", tags=["dofleet", "dofleet-exp-100"])
    old["volume_ids"] = ["vol-1"]
    fd.vols["vol-1"] = {"id": "vol-1", "name": "old-v1", "tags": ["dofleet"], "droplet_ids": [old["id"]]}
    fd.vols["vol-9"] = {"id": "vol-9", "name": "lost", "tags": ["dofleet"], "droplet_ids": [],
                        "created_at": "2020-01-01T00:00:00Z"}
    fd.add("fresh", tags=["dofleet", f"dofleet-exp-{int(time.time()) + 999}"])
    fd.add("hand", tags=["dofleet-exp-1"])
    http = httpx.Client(transport=fd.transport(), base_url="https://api.digitalocean.com/v2")

    def call(method, path, body=None, params=""):
        r = http.request(method, path + params, json=body)
        return r.status_code, (r.json() if r.content else {})
    dry = mod["reap"](call, time.time(), dry_run=True)
    assert dry["deleted"] == ["old"] and old["id"] in fd.droplets
    res = mod["reap"](call, time.time())
    assert res["deleted"] == ["old"] and res["orphan_volumes"] == ["lost"]
    assert {d["name"] for d in fd.droplets.values()} == {"fresh", "hand"} and fd.vols == {}
    fd.usage = "99"
    res = mod["reap"](call, time.time(), budget_usd=50)
    assert res["over_budget"] and res["deleted"] == ["fresh"]


def test_install_reaper_deploys_and_schedules(fake):
    seen = []

    def faas_host(req: httpx.Request):
        seen.append((req.method, req.url.path))
        if req.url.path == "/api/v1":
            return httpx.Response(200, json={"runtimes": {"python": [{"kind": "python:3.11"},
                                                                     {"kind": "python:3.12", "default": True}]}})
        if req.method == "PUT":
            body = json.loads(req.content)
            assert body["exec"]["kind"] == "python:3.12" and "def main(args)" in body["exec"]["code"]
            assert {p["key"] for p in body["parameters"]} >= {"token", "budget_usd"}
            return httpx.Response(200, json={})
        return httpx.Response(200, json={"body": {"checked": 0, "deleted": []}})
    fake.namespaces.append({"namespace": "fn-old", "label": "dofleet", "region": "sgp1", "api_host": "x", "uuid": "u"})
    out = faas.install(cli.S._client, "tok", region="sgp1", cron="*/10 * * * *", grace_s=0, budget_usd=5,
                       budget_action="reap", http=httpx.Client(transport=httpx.MockTransport(faas_host)))
    assert [n["namespace"] for n in fake.namespaces] == [out["namespace"]] != ["fn-old"]
    assert fake.triggers[0]["scheduled_details"]["cron"] == "*/10 * * * *"
    assert ("PUT", f"/api/v1/namespaces/{out['namespace']}/actions/dofleet-reap") in seen
    assert faas.uninstall(cli.S._client) == 1 and fake.namespaces == []


def mcp_call(server, tool, **args):
    reply = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": tool, "arguments": args}})
    res = reply["result"]
    return res["isError"], (json.loads(res["content"][0]["text"]) if not res["isError"] else res["content"][0]["text"])


def test_mcp_policy(fake):
    from dofleet import config
    server = mcp_server.Server(cli.S._client, config.load(fake.cfg),
                               run=lambda cmd, **k: subprocess.CompletedProcess(cmd, 0, "hi\n", ""))
    init = server.handle({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {"protocolVersion": "2025-06-18"}})
    assert init["result"]["serverInfo"]["name"] == "dofleet"
    names = [x["name"] for x in server.handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})["result"]["tools"]]
    assert "dofleet_create" in names and server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    is_err, text = mcp_call(server, "dofleet_create", preset="desktop")
    assert is_err and "not allowed" in text
    is_err, text = mcp_call(server, "dofleet_create", preset="tiny", ttl="9h")
    assert is_err and "longer than" in text
    is_err, out = mcp_call(server, "dofleet_create", preset="tiny", ttl="30m", name="bot")
    assert not is_err and out[0]["state"] == "ready" and out[0]["login_user"] == "ops"
    exp = fleet.expires_at(next(iter(fake.droplets.values())))
    assert abs(exp - (time.time() + 1800)) < 90
    is_err, out = mcp_call(server, "dofleet_exec", name="bot", command="uname -a")
    assert out == {"exit_code": 0, "stdout": "hi\n", "stderr": ""}
    is_err, out = mcp_call(server, "dofleet_extend", name="bot", ttl="3h")
    assert not is_err
    is_err, text = mcp_call(server, "dofleet_extend", name="bot", ttl="5h")
    assert is_err
    fake.add("prod-db")  # not a dofleet droplet: invisible to the agent
    is_err, text = mcp_call(server, "dofleet_delete", name="prod-db")
    assert is_err and "prod-db" in [d["name"] for d in fake.droplets.values()]
    for _ in range(2):
        mcp_call(server, "dofleet_create", preset="tiny", ttl="30m")
    is_err, text = mcp_call(server, "dofleet_create", preset="tiny", ttl="30m")
    assert is_err and "limit" in text
    is_err, out = mcp_call(server, "dofleet_delete", name="bot")
    assert not is_err and out["deleted"] == "bot"


def test_mcp_stdio_loop(fake):
    from dofleet import config
    lines = "\n".join(json.dumps(m) for m in [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "dofleet_list", "arguments": {}}},
        {"jsonrpc": "2.0", "id": 3, "method": "nope"}]) + "\nnot json\n"
    out = io.StringIO()
    mcp_server.serve(cli.S._client, config.load(fake.cfg), io.StringIO(lines), out)
    replies = [json.loads(x) for x in out.getvalue().splitlines()]
    assert [r.get("id") for r in replies] == [1, 2, 3, None]
    assert replies[2]["error"]["code"] == -32601 and replies[3]["error"]["code"] == -32700
