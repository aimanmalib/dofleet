"""Information and housekeeping commands: restart, ssh, cost, sizes, presets, init, whoami. Registered on cli.app."""

from __future__ import annotations

import os
import shutil
import time
from typing import Optional

import typer
from rich.table import Table

from . import budget, cloudinit, config, launch, ops, placement, ready, fleet
from .cli import S, _pick, app, con, confirm, err, money, out_json, say
from .i18n import t


@app.command("restart", help="Reboot droplets (--hard = power cycle)")
def restart(patterns: list[str] = typer.Argument(...), hard: bool = typer.Option(False, "--hard"),
            yes: bool = typer.Option(False, "--yes", "-y")):
    hits = _pick(patterns)
    if not confirm(t("restart.confirm", names=", ".join(d["name"] for d in hits)), yes):
        raise typer.Exit(1)
    for d in hits:
        S.client().droplet_action(d["id"], "power_cycle" if hard else "reboot")
    say(t("restart.done", n=len(hits)))


@app.command("ssh", help="SSH into a droplet by name")
def ssh(target: str, command: list[str] = typer.Argument(None, help="Optional command to run, after --"),
        user: Optional[str] = typer.Option(None, "--user", "-u")):
    hits = _pick([target])
    ip = ops.rows(hits[:1], time.time())[0]["ip"]
    if not ip:
        err.print(t("err.no_ip"))
        raise typer.Exit(1)
    user = user or launch.login_user(S.settings, hits[0])
    if not shutil.which("ssh"):
        err.print(t("err.no_ssh"))
        raise typer.Exit(1)
    args = ready.ssh_args(hits[0]["id"], ops.local_identity(S.settings), batch=False)
    os.execvp("ssh", ["ssh", *args, f"{user}@{ip}", *(command or [])])


@app.command("cost", help="Balance, this month's usage, and what the running fleet costs")
def cost():
    c = ops.cost_summary(S.client(), time.time())
    if S.as_json:
        out_json(c)
        return
    tb = Table(show_header=False, box=None)
    tb.add_row(t("cost.mtd"), money(c["month_to_date_usage"]))
    tb.add_row(t("cost.balance"), money(c["month_to_date_balance"]))
    tb.add_row(t("cost.fleet"), t("cost.fleet_v", n=c["droplets"], month=money(c["fleet_monthly"]),
                                  day=money(c["fleet_hourly"] * 24)))
    st = budget.status(S.client(), S.settings)
    if st.on:
        tb.add_row(t("plan.budget"), t("cost.budget_v", used=money(st.used), budget=money(st.budget), left=money(st.left)))
    con.print(tb)
    if (c.get("usage_age_h") or 0) >= 1:
        con.print(f"[dim]{t('cost.stale', hours=c['usage_age_h'])}[/]")
    if c["orphan_volumes"]:
        con.print(f"[yellow]{t('cost.orphans', n=len(c['orphan_volumes']), gb=c['orphan_volume_gb'], names=', '.join(c['orphan_volumes']))}[/]")
    if c["without_timer"]:
        con.print(f"[yellow]{t('cost.no_timer', n=c['without_timer'])}[/]")


@app.command("sizes", help="Sizes in stock, cheapest first")
def sizes(region: Optional[str] = typer.Option(None, "--region", "-r"),
          family: str = typer.Option("basic", "--family", "-f", help="basic | premium | cpu | memory | gpu | all")):
    data = placement.filter_sizes(S.client().sizes(), region, family)
    if S.as_json:
        out_json(data)
        return
    tb = Table("#", "slug", "vCPU", "RAM", "disk", t("col.monthly"), t("col.hourly"))
    for i, s in enumerate(data, 1):
        tb.add_row(str(i), s["slug"], str(s.get("vcpus")), fleet.mem_text(s.get('memory')),
                   f"{s.get('disk')} GB", money(float(s.get("price_monthly") or 0)), f"${float(s.get('price_hourly') or 0):.4f}")
    con.print(tb)


@app.command("presets", help="Presets and setup templates you can use")
def presets():
    if S.as_json:
        out_json({"presets": S.settings.presets, "templates": cloudinit.bundled_names()})
        return
    tb = Table(t("col.preset"), t("col.desc"), t("col.size"), t("col.timer"))
    for name, p in sorted(S.settings.presets.items()):
        tb.add_row(name, p.get("description", ""), " > ".join(p.get("sizes", [])), p.get("ttl") or "-")
    con.print(tb)
    for name in cloudinit.bundled_names():
        con.print(f"  [bold]{name}[/]  {cloudinit.describe(name)}")
    con.print(t("presets.where", path=S.settings.path))


@app.command("init", help="Write a starter config.toml")
def init():
    path = config.write_starter()
    con.print(t("init.done", path=path))


@app.command("whoami", help="Which account and token this profile uses")
def whoami():
    _, source = S.settings.token(S.profile)
    acc = S.client().account()
    data = {"email": acc.get("email"), "status": acc.get("status"), "droplet_limit": acc.get("droplet_limit"),
            "token_from": source}
    if S.as_json:
        out_json(data)
    else:
        con.print(t("whoami", **data))
