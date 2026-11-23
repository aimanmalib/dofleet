"""Commands beyond the basics: run, bake, install-reaper / uninstall-reaper, mcp. Registered on cli.app."""

from __future__ import annotations

import os
import shlex
import sys
import time
from pathlib import Path
from typing import Optional

import typer

from . import bake as bakemod, faas, fleet, launch, ops, runjob, volumes
from .cli import S, _kv, _pick, app, con, confirm, err, money, out_json, say, show_plan
from .config import ConfigError
from .i18n import t


@app.command("run", help="Run one command on a fresh droplet, copy results back, delete the droplet")
def run(preset: str = typer.Argument(..., help="Preset to boot"),
        command: list[str] = typer.Argument(..., help="Command to run on the droplet, after --"),
        sync: Optional[Path] = typer.Option(None, "--sync", help="Local folder copied to ~/work first"),
        pull: list[str] = typer.Option([], "--pull", help="Path under ~/work to copy back (repeatable)"),
        out: Path = typer.Option(Path("dofleet-out"), "--out", help="Where pulled files go"),
        env: list[str] = typer.Option([], "--env", help="KEY=VALUE for the command (repeatable)"),
        name: str = typer.Option("run", "--name", "-n"),
        ttl: Optional[str] = typer.Option(None, "--ttl", help="Backstop timer; default = the preset's"),
        size: list[str] = typer.Option([], "--size", "-s"),
        volume: list[int] = typer.Option([], "--volume"),
        keep: bool = typer.Option(False, "--keep", help="Leave the droplet running afterwards (timer still applies)"),
        keep_on_fail: bool = typer.Option(False, "--keep-on-fail", help="Leave it running only if the command fails"),
        baked: bool = typer.Option(False, "--baked"),
        yes: bool = typer.Option(False, "--yes", "-y")):
    client = S.client()
    ov = ops.Overrides(sizes=size, ttl=ttl, volumes=volume, baked=baked)
    with con.status(t("up.planning")):
        plan = ops.plan_up(client, S.settings, preset, name, 1, ov)
    show_plan(plan)
    if not plan.ttl_s:
        err.print(f"[red]{t('err.run_needs_ttl')}[/]")
        raise typer.Exit(2)
    if not confirm(t("up.confirm", n=1), yes):
        raise typer.Exit(1)
    started = time.time()
    res: dict = {}
    made: list[dict] = []
    rc = 1
    try:
        with con.status(t("run.booting")):
            res = launch.create_and_wait(client, S.settings, plan, on_created=made.extend)
        r = next(iter(res.values()))
        if r["state"] != "ready":
            err.print(f"[red]{t('run.not_ready', state=t('state.' + r['state']))}[/]")
            raise typer.Exit(1)
        did, ip, ident = r["droplet"]["id"], r["ip"], ops.local_identity(S.settings)
        user = launch.login_user(S.settings, r["droplet"])
        if sync:
            with con.status(t("run.upload", path=sync)):
                runjob.upload(did, ip, user, ident, sync)
        say(f"[dim]$ {shlex.join(command)}[/]")
        rc = runjob.execute(did, ip, user, ident, command, dict(_kv(e) for e in env))
        if pull:
            dest = out / r["droplet"]["name"]
            runjob.download(did, ip, user, ident, pull, dest)
            say(t("run.pulled", path=dest))
    except runjob.JobError as e:
        err.print(f"[red]{t(e.key, **e.kw)}[/]")
    finally:
        keep_it = keep or (keep_on_fail and rc != 0)
        for d in made:  # everything that was created, even if waiting failed half way
            r = res.get(d["id"]) or {"droplet": d, "ip": None}
            if keep_it:
                say(t("run.kept", name=d.get("name"), ip=r["ip"]))
            else:
                volumes.destroy(client, client.droplet(d["id"]))
        spent = plan.size.get("price_hourly", 0) * max(1 / 60, (time.time() - started) / 3600)
        say(t("run.done", rc=rc, mins=f"{(time.time() - started) / 60:.1f}", cost=money(float(spent))))
    if S.as_json:
        out_json({"exit_code": rc, "droplets": [d.get("name") for d in made]})
    raise typer.Exit(rc)


@app.command("bake", help="Snapshot a finished droplet so `up --baked` boots in seconds")
def bake(target: str = typer.Argument(..., help="Droplet name or id"),
         yes: bool = typer.Option(False, "--yes", "-y")):
    d = _pick([target])[0]
    keep = int(S.settings.defaults.get("bake_keep", 1))
    if not confirm(t("bake.confirm", name=d["name"], keep=keep), yes):
        raise typer.Exit(1)
    with con.status(t("bake.working", name=d["name"])):
        result = bakemod.bake(S.client(), d, keep)
    if S.as_json:
        out_json(result)
    else:
        con.print(t("bake.done", **{**result, "removed": ", ".join(result["removed"]) or "-"}))


@app.command("snapshots", help="dofleet snapshots made by `bake`")
def snapshots():
    data = bakemod.snapshots(S.client())
    if S.as_json:
        out_json(data)
        return
    for s in data:
        con.print(f"{s['name']}  {s.get('size_gigabytes')} GB  {', '.join(s.get('regions', []))}")
    if not data:
        con.print(t("bake.none"))


@app.command("install-reaper", help="Run the reaper as a scheduled DigitalOcean Function (no cron needed)")
def install_reaper(region: Optional[str] = typer.Option(None, "--region", help="Functions region, e.g. sgp1, nyc1"),
                   every: str = typer.Option("10m", "--every", help="How often: 5m, 10m, 30m, 1h"),
                   token_env: Optional[str] = typer.Option(None, "--token-env",
                                                           help="Env var with a separate token for the reaper"),
                   notify_url: str = typer.Option("", "--notify-url", help="Webhook (Slack/Discord style) for reports"),
                   yes: bool = typer.Option(False, "--yes", "-y")):
    cron = faas.every_to_cron(fleet.parse_duration(every))
    token = os.environ.get(token_env, "") if token_env else S.settings.token(S.profile)[0]
    if not token:
        err.print(f"[red]{t('err.no_token', profile=token_env, envs=token_env)}[/]")
        raise typer.Exit(1)
    region = region or S.settings.defaults.get("functions_region", "sgp1")
    if not confirm(t("faas.confirm", region=region, cron=cron), yes):
        raise typer.Exit(1)
    g = str(S.settings.defaults.get("reap_grace") or "0m")
    with con.status(t("faas.working")):
        result = faas.install(S.client(), token, region=region, cron=cron,
                              grace_s=0 if g.strip() in ("", "0", "0m") else fleet.parse_duration(g),
                              budget_usd=float(S.settings.defaults.get("budget_usd") or 0),
                              budget_action=str(S.settings.defaults.get("budget_action") or "reap"),
                              notify_url=notify_url)
    if S.as_json:
        out_json(result)
    else:
        tr = result["test_run"]
        con.print(t("faas.done", region=region, cron=cron, checked=tr.get("checked", "?"),
                    would=", ".join(tr.get("deleted", [])) or "-"))


@app.command("uninstall-reaper", help="Remove the scheduled DigitalOcean Function reaper")
def uninstall_reaper(yes: bool = typer.Option(False, "--yes", "-y")):
    if not confirm(t("faas.uninstall_confirm"), yes):
        raise typer.Exit(1)
    n = faas.uninstall(S.client())
    say(t("faas.uninstalled", n=n))


@app.command("mcp", help="MCP server on stdio: let an AI agent borrow droplets under your policy")
def mcp():
    from .mcp_server import MissingToken, serve
    try:
        client = S.client()
    except ConfigError as e:  # still answer initialize and tools/list; tool calls report the missing token
        client = MissingToken(e)
    serve(client, S.settings, sys.stdin, sys.stdout)
