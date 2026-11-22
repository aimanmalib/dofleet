import json
import time

import pytest
from typer.testing import CliRunner

from dofleet import cli, fleet, ops, ready
from dofleet.api import ApiError, DOClient
from fake_do import FakeDO

runner = CliRunner()


@pytest.fixture
def fake(monkeypatch, tmp_path):
    fd = FakeDO()
    monkeypatch.setenv("DOFLEET_CONFIG", str(tmp_path / "config.toml"))
    monkeypatch.setenv("DOFLEET_LANG", "en")
    monkeypatch.setenv("DIGITALOCEAN_TOKEN", "t")
    cli.S._client = DOClient("t", transport=fd.transport(), sleep=lambda s: None)
    monkeypatch.setattr(ready, "port_open", lambda ip, port, timeout=5.0: True)
    monkeypatch.setattr(ready, "cloud_init_state", lambda ip, identity=None: "done")
    monkeypatch.setenv("HOME", str(tmp_path))  # no real ~/.ssh keys leak into tests
    monkeypatch.setattr(ready.time, "sleep", lambda s: None)
    yield fd
    cli.S._client = None


def run(*args):
    return runner.invoke(cli.app, list(args), catch_exceptions=False)


def test_up_falls_back_tags_and_waits(fake):
    r = run("--json", "up", "quick", "-n", "job", "-c", "3", "--yes", "--tag", "ci run")
    assert r.exit_code == 0, r.output
    out = json.loads(r.output)
    assert out["region"] == "sgp1" and out["size"] == "s-4vcpu-8gb-amd" and out["fallback"] is True
    assert [d["state"] for d in out["droplets"]] == ["ready"] * 3
    body = fake.created_bodies[0]
    assert body["names"] == ["job-01", "job-02", "job-03"] and body["ssh_keys"] == [11]
    assert "dofleet" in body["tags"] and "dofleet-preset-quick" in body["tags"] and "ci-run" in body["tags"]
    exp = [t for t in body["tags"] if t.startswith(fleet.EXP_PREFIX)]
    assert len(exp) == 1 and abs(int(exp[0][len(fleet.EXP_PREFIX):]) - (time.time() + 8 * 3600)) < 60
    assert body["user_data"].startswith("#!/bin/bash") and "PasswordAuthentication no" in body["user_data"]
    assert out["cost_month_usd"] == 168.0 and out["cost_until_expiry_usd"] == pytest.approx(8 * 0.08333 * 3, abs=0.01)


def test_up_sold_out_at_create_moves_on(fake):
    fake.sold_out.add(("sgp1", "s-4vcpu-8gb-amd"))
    r = run("--json", "up", "quick", "--yes", "--no-wait")
    assert r.exit_code == 0, r.output
    assert [(b["region"], b["size"]) for b in fake.created_bodies] == [("sgp1", "s-4vcpu-8gb-amd"), ("blr1", "s-4vcpu-8gb")]


def test_up_batches_of_ten(fake):
    r = run("--json", "up", "tiny", "-c", "12", "--yes", "--no-wait", "--keep")
    assert r.exit_code == 0, r.output
    assert [len(b["names"]) for b in fake.created_bodies] == [10, 2]
    assert not any(t.startswith(fleet.EXP_PREFIX) for t in fake.created_bodies[0]["tags"])


def test_up_without_any_key_keeps_root_password_login(fake):
    fake.keys = []
    r = run("--json", "up", "tiny", "--yes", "--no-wait")
    ud = fake.created_bodies[0]["user_data"]
    assert "PasswordAuthentication yes" in ud and "PermitRootLogin yes" in ud, r.output
    assert fake.created_bodies[0]["ssh_keys"] == []


def test_up_uploads_local_key_when_account_has_none(fake, tmp_path):
    fake.keys = []
    (tmp_path / ".ssh").mkdir()
    (tmp_path / ".ssh" / "id_ed25519.pub").write_text("ssh-ed25519 AAAAC3Nza test@host\n")
    r = run("--json", "up", "tiny", "--yes", "--no-wait")
    assert r.exit_code == 0, r.output
    body = fake.created_bodies[0]
    assert body["ssh_keys"] == [99] and "PermitRootLogin prohibit-password" in body["user_data"]
    run("--json", "up", "tiny", "--yes", "--no-wait")  # second run reuses the uploaded key
    assert [c for c in fake.calls if c == ("POST", "/account/keys")] == [("POST", "/account/keys")]


def test_create_is_not_retried_on_5xx(fake):
    fake.fail_next = []
    c = cli.S._client
    fake_calls_before = len(fake.calls)
    fake.fail_next = [500]
    with pytest.raises(ApiError):
        c.create_droplets({"names": ["x"], "region": "sgp1", "size": "s-1vcpu-1gb"})
    assert len(fake.calls) - fake_calls_before == 1 and fake.droplets == {}


def test_reap_notifies_and_survives_errors(fake, monkeypatch, tmp_path):
    a = fake.add("a", tags=["dofleet", "dofleet-exp-1"])
    b = fake.add("b", tags=["dofleet", "dofleet-exp-1"])
    c = fake.add("c", tags=["dofleet", "dofleet-exp-1"])
    fake.delete_errors = {a["id"]: 404, b["id"]: 500}
    log = tmp_path / "n.txt"
    (tmp_path / "config.toml").write_text(f'[defaults]\nnotify_cmd = ["sh", "-c", "echo \\"$0\\" >> {log}"]\n')
    r = runner.invoke(cli.app, ["--json", "reap", "--yes"])
    out = json.loads(r.stdout)
    assert r.exit_code == 1 and sorted(out["deleted"]) == sorted([a["id"], c["id"]]) and out["failed"] == [b["id"]]
    assert "deleted 2 expired" in log.read_text()


def test_dry_run_creates_nothing(fake):
    r = run("--json", "up", "desktop", "--dry-run")
    assert r.exit_code == 0 and fake.created_bodies == []
    assert "xrdp" in json.loads(r.output)["user_data"]


def test_not_a_terminal_needs_yes(fake):
    r = run("up", "tiny")
    assert r.exit_code == 2 and fake.created_bodies == []


def test_big_batch_needs_typed_count(fake, monkeypatch):
    monkeypatch.setattr(cli, "confirm", lambda prompt, assume: True)
    r = runner.invoke(cli.app, ["up", "quick", "-c", "2", "--no-wait"], input="1\n")
    assert r.exit_code == 1 and fake.created_bodies == []  # 2 x $56 > $50 limit, wrong number typed
    r = runner.invoke(cli.app, ["up", "quick", "-c", "2", "--no-wait"], input="2\n")
    assert r.exit_code == 0 and len(fake.created_bodies) == 1, r.output


def test_ls_and_cost(fake):
    fake.add("old", tags=["dofleet", "dofleet-exp-1"])
    fake.add("pet")
    fake.add("x3")  # 3 droplets with page size 2 -> pagination exercised
    out = json.loads(run("--json", "ls").output)
    assert [r["name"] for r in out][0] == "old" and out[0]["expires_in_s"] < 0
    assert {r["name"] for r in out} == {"old", "pet", "x3"}
    managed = json.loads(run("--json", "ls", "-m").output)
    assert [r["name"] for r in managed] == ["old"]
    c = json.loads(run("--json", "cost").output)
    assert c["droplets"] == 3 and c["fleet_monthly"] == 18.0 and c["without_timer"] == 2
    assert c["month_to_date_usage"] == 12.5


def test_reap_only_expired_managed(fake):
    old = fake.add("old", tags=["dofleet", "dofleet-exp-1"])
    fake.add("fresh", tags=["dofleet", f"dofleet-exp-{int(time.time()) + 3600}"])
    fake.add("foreign", tags=["dofleet-exp-1"])  # not ours: no marker tag
    dry = json.loads(run("--json", "reap", "--dry-run").output)
    assert dry["expired"] == [old["id"]] and old["id"] in fake.droplets
    out = json.loads(run("--json", "reap", "--yes").output)
    assert out["deleted"] == [old["id"]]
    assert {d["name"] for d in fake.droplets.values()} == {"fresh", "foreign"}


def test_extend_and_keep(fake):
    d = fake.add("box", tags=["dofleet", "dofleet-exp-100"])
    out = json.loads(run("--json", "extend", "box", "--ttl", "1h").output)
    new = out[0]["expires_at"]
    assert abs(new - (time.time() + 3600)) < 60
    assert d["tags"].count(f"dofleet-exp-{new}") == 1 and "dofleet-exp-100" not in d["tags"]
    json.loads(run("--json", "extend", "box", "--keep").output)
    assert not any(t.startswith(fleet.EXP_PREFIX) for t in d["tags"])


def test_down_glob_spares_unmanaged(fake):
    fake.add("web-01", tags=["dofleet"]), fake.add("web-02"), fake.add("db")
    out = json.loads(runner.invoke(cli.app, ["--json", "down", "web-*", "--yes"]).stdout)
    assert len(out["deleted"]) == 1 and {d["name"] for d in fake.droplets.values()} == {"web-02", "db"}
    out = json.loads(runner.invoke(cli.app, ["--json", "down", "web-*", "--yes", "--any"]).stdout)
    assert len(out["deleted"]) == 1 and [d["name"] for d in fake.droplets.values()] == ["db"]
    out = json.loads(runner.invoke(cli.app, ["--json", "down", "db", "--yes"]).stdout)  # exact name always works
    assert len(out["deleted"]) == 1 and fake.droplets == {}
    assert run("down", "nothing", "--yes").exit_code == 1


def test_retry_on_429_then_success():
    fd = FakeDO()
    fd.fail_next = [429, 503]
    c = DOClient("t", transport=fd.transport(), sleep=lambda s: None)
    assert c.account()["email"] == "a@example.com"
    fd.fail_next = [401]
    with pytest.raises(ApiError) as e:
        c.account()
    assert e.value.status == 401


def test_wait_ready_waits_for_setup():
    fd = FakeDO()
    d1, d2 = fd.add("ok", status="new", ip=None), fd.add("bad", status="new", ip=None)
    c = DOClient("t", transport=fd.transport())
    states = {d1["id"]: iter(["running", "done"]), d2["id"]: iter(["failed"])}
    ip_to_id = {}

    def setup(ip):
        return next(states[ip_to_id[ip]])
    orig = c.droplet

    def droplet(i):
        d = orig(i)
        ip_to_id[d["networks"]["v4"][0]["ip_address"]] = i
        return d
    c.droplet = droplet
    res = ready.wait_ready(c, [d1["id"], d2["id"]], 22, 1000, probe=lambda ip, p: True, sleep=lambda s: None,
                           setup=setup)
    assert res[d1["id"]]["state"] == "ready" and res[d2["id"]]["state"] == "setup_failed"


def test_wait_ready_times_out():
    fd = FakeDO()
    d = fd.add("slow", status="new", ip=None)
    c = DOClient("t", transport=fd.transport())
    clock = iter(range(0, 1000, 100))
    res = ready.wait_ready(c, [d["id"]], 22, 250, probe=lambda ip, p: False, sleep=lambda s: None,
                           clock=lambda: next(clock))
    assert res[d["id"]]["state"] == "timeout" and res[d["id"]]["ip"]


def test_malay_output(fake, monkeypatch):
    monkeypatch.setenv("DOFLEET_LANG", "ms")
    r = run("ls")
    assert "Tiada droplet." in r.output


def test_errors_are_translated(fake, monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["dofleet", "up", "nope"])
    with pytest.raises(SystemExit) as e:
        cli.main()
    assert e.value.code == 1
    assert "No preset named 'nope'" in capsys.readouterr().err


def test_menu_dispatches_to_commands(fake, monkeypatch, capsys):
    from dofleet import menu
    fake.add("box", tags=["dofleet", "dofleet-exp-1"])
    cli.S.settings = cli.config.load()
    cli.S.as_json = False
    answers = iter(["2", "5", "8"])
    monkeypatch.setattr(menu.typer, "prompt", lambda *a, **k: next(answers))
    monkeypatch.setattr(cli, "confirm", lambda prompt, assume: True)
    menu.run_menu(cli)
    assert fake.droplets == {}  # "5" = reap deleted the expired droplet


def test_volumes_created_per_droplet_and_reaped_together(fake):
    hand = {"id": "vol-hand", "name": "manual", "region": "sgp1", "size_gigabytes": 5, "tags": []}
    out = json.loads(run("--json", "up", "scratch", "-c", "2", "--yes", "--no-wait").output)
    assert [len(b["names"]) for b in fake.created_bodies] == [1, 1]  # one droplet per call
    assert [b["volumes"] for b in fake.created_bodies] == [["vol-1"], ["vol-2"]]
    assert out["cost_month_usd"] == 2 * (56 + 10)  # droplet + 100 GB at $0.10
    fake.vols["vol-hand"] = hand
    first = fake.droplets[min(fake.droplets)]
    first["volume_ids"].append("vol-hand")  # attached by hand: must survive
    for d in fake.droplets.values():
        d["tags"] = ["dofleet", "dofleet-exp-1"]
    out = json.loads(run("--json", "reap", "--yes").output)
    assert len(out["deleted"]) == 2 and fake.droplets == {} and list(fake.vols) == ["vol-hand"]


def test_volume_cleanup_when_create_fails(fake):
    fake.sold_out = {("sgp1", "s-4vcpu-8gb-amd"), ("blr1", "s-4vcpu-8gb"), ("blr1", "s-4vcpu-8gb-amd")}
    r = runner.invoke(cli.app, ["--json", "up", "scratch", "--yes", "--no-wait"])
    assert r.exit_code != 0 and len(fake.created_bodies) == 1 and fake.vols == {} and fake.droplets == {}
