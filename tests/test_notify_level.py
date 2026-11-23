"""Reap notifications carry a level (D11): timer ran out = info, budget kill = warn, failed delete = critical.

Everything goes through ``cli.app`` so these tests run (and fail) on code that predates levels.
"""

import json
import time

from typer.testing import CliRunner

from dofleet import cli

runner = CliRunner()


def _config(fake, log, cmd_tail, extra=""):
    script = f"printf '%s|%s\\\\n' \\\"$0\\\" \\\"$1\\\" >> {log}"
    fake.cfg.write_text(f'[defaults]\n{extra}notify_cmd = ["sh", "-c", "{script}"{cmd_tail}]\n')


def _reap():
    r = runner.invoke(cli.app, ["--json", "reap", "--yes"])
    return r, json.loads(r.stdout)


def _lines(log):
    return log.read_text().splitlines() if log.exists() else []


def test_expired_reap_is_info_and_placeholders_are_filled(fake, tmp_path):
    fake.add("dfl-faas", tags=["dofleet", "dofleet-exp-1"])
    log = tmp_path / "n.log"
    _config(fake, log, ', "{message}", "{level}"')
    r, out = _reap()
    assert r.exit_code == 0 and len(out["deleted"]) == 1
    [line] = _lines(log)
    assert line.endswith("|info") and "dfl-faas" in line and "{message}" not in line
    assert "nothing to do" in line.lower()


def test_failed_delete_sends_critical(fake, tmp_path):
    ok = fake.add("a", tags=["dofleet", "dofleet-exp-1"])
    bad = fake.add("stuck", tags=["dofleet", "dofleet-exp-1"])
    fake.delete_errors = {bad["id"]: 500}
    log = tmp_path / "n.log"
    _config(fake, log, ', "{message}", "{level}"')
    r, out = _reap()
    assert r.exit_code == 1 and out["deleted"] == [ok["id"]] and out["failed"] == [bad["id"]]
    lines = _lines(log)
    assert [ln.rsplit("|", 1)[1] for ln in lines] == ["info", "critical"]
    assert "stuck" in lines[1] and "stuck" not in lines[0]


def test_failed_only_still_notifies(fake, tmp_path):
    bad = fake.add("stuck", tags=["dofleet", "dofleet-exp-1"])
    fake.delete_errors = {bad["id"]: 500}
    log = tmp_path / "n.log"
    _config(fake, log, ', "{message}", "{level}"')
    r, _ = _reap()
    assert r.exit_code == 1
    [line] = _lines(log)
    assert line.endswith("|critical") and "stuck" in line


def test_budget_kill_is_warn(fake, tmp_path):
    fake.add("old", tags=["dofleet", "dofleet-exp-1"])
    fake.add("fresh", tags=["dofleet", f"dofleet-exp-{int(time.time()) + 9999}"])
    log = tmp_path / "n.log"
    _config(fake, log, ', "{message}", "{level}"', extra='budget_usd = 10\nbudget_action = "reap"\n')
    r, out = _reap()
    assert r.exit_code == 0 and len(out["deleted"]) == 2
    levels = {ln.rsplit("|", 1)[1]: ln for ln in _lines(log)}
    assert set(levels) == {"info", "warn"}
    assert "fresh" in levels["warn"] and "old" in levels["info"] and "budget" in levels["warn"]


def test_old_form_still_gets_the_message_appended(fake, tmp_path):
    fake.add("a", tags=["dofleet", "dofleet-exp-1"])
    log = tmp_path / "n.txt"
    fake.cfg.write_text(f'[defaults]\nnotify_cmd = ["sh", "-c", "echo \\"$0\\" >> {log}"]\n')
    r, _ = _reap()
    assert r.exit_code == 0
    [line] = _lines(log)
    assert "deleted 1 expired" in line and line.rstrip().endswith("2h")


def test_braces_in_droplet_names_pass_through(fake, tmp_path):
    fake.add("x{level}y{}", tags=["dofleet", "dofleet-exp-1"])
    log = tmp_path / "n.log"
    _config(fake, log, ', "{message}", "{level}"')
    r, _ = _reap()
    assert r.exit_code == 0
    [line] = _lines(log)
    assert "x{level}y{}" in line and line.endswith("|info")


def test_build_argv_is_standalone():
    from dofleet.notify import build_argv  # inside the test: the module is new

    assert build_argv(["n.sh", "{message}", "{level}"], "m {level}", "warn") == ["n.sh", "m {level}", "warn"]
    assert build_argv(["n.sh"], "m", "info") == ["n.sh", "m"]
    assert build_argv("n.sh", "m", "critical") == ["n.sh", "m"]
    assert build_argv(["n.sh", "--level={level}", "--text={message}"], "m", "info") == ["n.sh", "--level=info", "--text=m"]
    assert build_argv([], "m", "info") == []
