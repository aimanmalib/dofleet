"""Reap removes the empty timer tags each droplet leaves behind, and nothing else (docs/DECISIONS.md D15).

DigitalOcean keeps a tag after the last resource carrying it is gone, so every droplet used to leave one
`dofleet-exp-<time>` tag in the account for good.
"""

import json
import time
from importlib import resources

import httpx
from typer.testing import CliRunner

from dofleet import cli
from fake_do import FakeDO

runner = CliRunner()
HOUR = 3600


def _seed(fd: FakeDO, now: int) -> dict:
    """Tags that must go, and tags that must stay, in one account."""
    names = {
        "gone": f"dofleet-exp-{now - 2 * HOUR}",          # droplet deleted long ago: empty, old -> removed
        "gone_detached": f"dofleet-detached-{now - 3 * HOUR}",  # volume deleted: empty, old -> removed
        "recent": f"dofleet-exp-{now - 60}",              # empty but under an hour old -> kept this run
        "future": f"dofleet-exp-{now + HOUR}",            # empty future timer (being created) -> kept
        "fresh_detached": f"dofleet-detached-{now}",      # a sweep just stamped it -> kept
    }
    for n in names.values():
        fd.tag_names[n] = None
    for n in ("dofleet", "dofleet-preset-tiny", "prod", "dofleet-exp-soon"):  # not timer tags -> kept
        fd.tag_names[n] = None
    # old timer tag still on a droplet dofleet does not manage (no marker): reap leaves the droplet and the tag
    fd.add("hand-made", tags=["web", f"dofleet-exp-{now - 5 * HOUR}"])
    return names


def test_reap_removes_only_old_empty_timer_tags(fake):
    now = int(time.time())
    names = _seed(fake, now)
    r = runner.invoke(cli.app, ["--json", "reap", "--yes"])
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert sorted(out["tags_removed"]) == sorted([names["gone"], names["gone_detached"]])
    left = set(fake.tag_names)
    assert names["gone"] not in left and names["gone_detached"] not in left
    assert {names["recent"], names["future"], names["fresh_detached"], "dofleet", "prod", "dofleet-exp-soon"} <= left
    assert f"dofleet-exp-{now - 5 * HOUR}" in fake.droplets[min(fake.droplets)]["tags"]  # in use: untouched


def test_dry_run_removes_no_tags(fake):
    names = _seed(fake, int(time.time()))
    out = json.loads(runner.invoke(cli.app, ["--json", "reap", "--dry-run"]).stdout)
    assert out["tags_removed"] == [] and names["gone"] in fake.tag_names
    assert not any(m == "DELETE" and p.startswith("/tags/") for m, p in fake.calls)


def test_timer_tag_of_a_reaped_droplet_goes_on_a_later_run(fake):
    now = int(time.time())
    old = fake.add("old", tags=["dofleet", f"dofleet-exp-{now - 2 * HOUR}"])  # missed while the host was down
    first = json.loads(runner.invoke(cli.app, ["--json", "reap", "--yes"]).stdout)
    assert first["deleted"] == [old["id"]]
    assert first["tags_removed"] == []  # the droplet still carried it when the sweep looked
    second = json.loads(runner.invoke(cli.app, ["--json", "reap", "--yes"]).stdout)
    assert second["tags_removed"] == [f"dofleet-exp-{now - 2 * HOUR}"]


def test_token_without_tag_scope_still_reaps(fake):
    now = int(time.time())
    _seed(fake, now)
    old = fake.add("old", tags=["dofleet", f"dofleet-exp-{now - 10}"])
    fake.tags_status = 403
    r = runner.invoke(cli.app, ["--json", "reap", "--yes"])
    assert r.exit_code == 0, r.output
    out = json.loads(r.stdout)
    assert out["deleted"] == [old["id"]] and out["tags_removed"] == []


def test_human_output_says_how_many_tags_went(fake):
    _seed(fake, int(time.time()))
    r = runner.invoke(cli.app, ["reap", "--yes"])
    assert r.exit_code == 0, r.output
    assert "Removed 2 empty dofleet tag(s)" in r.output


def test_function_reaper_sweeps_the_same_tags():
    spec = resources.files("dofleet").joinpath("data", "reaper_function.py").read_text()
    mod = {}
    exec(compile(spec, "reaper_function.py", "exec"), mod)
    fd = FakeDO()
    now = int(time.time())
    names = _seed(fd, now)
    http = httpx.Client(transport=fd.transport(), base_url="https://api.digitalocean.com/v2")

    def call(method, path, body=None, params=""):
        r = http.request(method, path + params, json=body)
        return r.status_code, (r.json() if r.content else {})
    assert mod["reap"](call, now, dry_run=True)["tags_removed"] == []
    res = mod["reap"](call, now)
    assert sorted(res["tags_removed"]) == sorted([names["gone"], names["gone_detached"]])
    assert names["recent"] in fd.tag_names and f"dofleet-exp-{now - 5 * HOUR}" in fd.droplets[min(fd.droplets)]["tags"]
    fd.tags_status = 403
    assert mod["reap"](call, now)["tags_removed"] == []  # housekeeping never breaks the reap
