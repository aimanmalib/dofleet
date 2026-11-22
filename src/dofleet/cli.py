"""Command line. `dofleet` with no arguments in a terminal opens the menu."""

from __future__ import annotations

import json
import os
import sys
import time
from typing import Optional

import typer
from rich.console import Console
from rich.markup import escape
from rich.table import Table

from . import __version__, budget, cloudinit, config, fleet, launch, ops, volumes
from .api import ApiError, DOClient
from .i18n import set_lang, t, resolve

app = typer.Typer(add_completion=False, no_args_is_help=False, rich_markup_mode=None, pretty_exceptions_enable=False,
                  help="Disposable DigitalOcean droplets with a cost guard.")
con = Console()
err = Console(stderr=True)


class State:
    profile: Optional[str] = None
    as_json = False
    settings: Optional[config.Settings] = None
    _client: Optional[DOClient] = None

    def client(self) -> DOClient:
        if self._client is None:
            token, _ = self.settings.token(self.profile)
            self._client = DOClient(token)
        return self._client


S = State()


def out_json(data) -> None:
    con.print_json(json.dumps(data, default=str))


def say(text: str) -> None:
    """Human text; silent in --json mode so stdout stays valid JSON."""
    if not S.as_json:
        con.print(text)


def money(x: float) -> str:
    return "<$0.01" if 0 < x < 0.005 else f"${x:,.2f}"


def confirm(prompt: str, assume: bool) -> bool:
    if assume:
        return True
    if not sys.stdin.isatty():
        err.print(t("err.need_yes"))
        raise typer.Exit(2)
    return typer.confirm(prompt, default=False)


@app.callback(invoke_without_command=True)
def root(ctx: typer.Context,
         profile: Optional[str] = typer.Option(None, "--profile", "-p", help="Account profile from config.toml"),
         lang: Optional[str] = typer.Option(None, "--lang", help="en | ms"),
         as_json: bool = typer.Option(False, "--json", help="Machine-readable output"),
         version: bool = typer.Option(False, "--version")):
    S.settings = config.load()
    set_lang(resolve(lang, S.settings.defaults.get("lang")))
    S.profile, S.as_json = profile, as_json
    for w in S.settings.warnings:
        err.print(f"[yellow]{t(w, path=S.settings.path)}[/]")
    if version:
        con.print(f"dofleet {__version__}")
        raise typer.Exit()
    if ctx.invoked_subcommand is None:
        if sys.stdin.isatty() and not as_json:
            from .menu import run_menu
            run_menu(sys.modules[__name__])
        else:
            con.print(ctx.get_help())


@app.command("up", help="Create droplets from a preset")
def up(preset: Optional[str] = typer.Argument(None),
       name: Optional[str] = typer.Option(None, "--name", "-n", help="Name or prefix"),
       count: int = typer.Option(1, "--count", "-c"),
       ttl: Optional[str] = typer.Option(None, "--ttl", help="Expiry timer, e.g. 30m 2h 3d. Empty string = none"),
       keep: bool = typer.Option(False, "--keep", help="No expiry timer"),
       region: list[str] = typer.Option([], "--region", "-r"),
       size: list[str] = typer.Option([], "--size", "-s"),
       image: Optional[str] = typer.Option(None, "--image"),
       tag: list[str] = typer.Option([], "--tag"),
       var: list[str] = typer.Option([], "--var", help="Template value, key=value"),
       volume: list[int] = typer.Option([], "--volume", help="Add a block storage volume of this many GB (repeatable)"),
       yes: bool = typer.Option(False, "--yes", "-y"),
       baked: bool = typer.Option(False, "--baked", help="Boot from the newest `dofleet bake` snapshot of this preset"),
       dry_run: bool = typer.Option(False, "--dry-run"),
       no_wait: bool = typer.Option(False, "--no-wait")):
    preset = preset or S.settings.defaults.get("preset", "quick")
    ov = ops.Overrides(region, size, image, "" if keep else ttl, tag, dict(_kv(v) for v in var), volume, baked)
    client = S.client()
    with con.status(t("up.planning")):
        plan = ops.plan_up(client, S.settings, preset, name, count, ov)
    show_plan(plan)
    if dry_run:
        if S.as_json:
            out_json({**_plan_dict(plan), "user_data": plan.user_data})
        return
    if not confirm(t("up.confirm", n=len(plan.names)), yes):
        raise typer.Exit(1)
    limit = float(S.settings.defaults.get("confirm_over_usd", 50))
    if plan.cost_month > limit and not yes:
        typed = typer.prompt(t("up.big_confirm", total=money(plan.cost_month), limit=money(limit)), default="")
        if typed.strip() != str(len(plan.names)):
            raise typer.Exit(1)
    port = int(plan.preset.get("ready_port", 22))
    with con.status(t("up.waiting", port=port)) as st:
        res = launch.create_and_wait(client, S.settings, plan, wait=not no_wait, on_update=lambda s: st.update(
            t("up.progress", ready=sum(v == "ready" for v in s.values()), total=len(s), port=port)))
    _finish(plan, res)


def _kv(text: str) -> tuple[str, str]:
    if "=" not in text:
        raise typer.BadParameter(text)
    k, v = text.split("=", 1)
    return k.strip(), v.strip()


def _plan_dict(plan: ops.Plan) -> dict:
    return {"preset": plan.preset["name"], "region": plan.region, "size": plan.size["slug"], "fallback": plan.fell_back,
            "names": plan.names, "image": plan.image, "ttl_s": plan.ttl_s, "ssh_keys": len(plan.ssh_key_ids),
            "cost_until_expiry_usd": round(plan.cost_ttl, 2), "cost_month_usd": round(plan.cost_month, 2)}


def _tilde(path: str) -> str:
    home = os.path.expanduser("~")
    return "~" + path[len(home):] if path.startswith(home + os.sep) else path


def show_plan(plan: ops.Plan) -> None:
    if S.as_json:
        return
    s = plan.size
    tb = Table(show_header=False, box=None, pad_edge=False)
    tb.add_row(t("plan.preset"), plan.preset["name"])
    tb.add_row(t("plan.where"), f"{plan.region}  {s['slug']}  ({s.get('vcpus')} vCPU / {fleet.mem_text(s.get('memory'))} / {s.get('disk')} GB)")
    if plan.fell_back:
        tb.add_row("", f"[yellow]{t('plan.fallback', want=f'{plan.regions_tried[0]} {plan.sizes_tried[0]}')}[/]")
    tb.add_row(t("plan.names"), ", ".join(plan.names))
    tb.add_row(t("plan.image"), plan.image)
    if plan.ssh_key_ids:
        tb.add_row(t("plan.keys"), str(len(plan.ssh_key_ids)))
    elif plan.upload_key:
        tb.add_row(t("plan.keys"), t("plan.upload_key", path=_tilde(plan.upload_key[0])))
    else:
        tb.add_row(t("plan.keys"), f"[yellow]{t('plan.no_keys')}[/]")
    tb.add_row(t("plan.timer"), fleet.format_duration(plan.ttl_s) if plan.ttl_s else f"[yellow]{t('plan.no_timer')}[/]")
    tb.add_row(t("plan.setup"), plan.preset.get("cloud_init") or "-")
    if plan.preset.get("volumes"):
        tb.add_row(t("plan.volumes"), t("plan.volumes_v", sizes=" + ".join(f"{g} GB" for g in volumes.sizes_gb(plan.preset))))
    if plan.ttl_s:
        tb.add_row(t("plan.cost"), t("plan.cost_ttl", ttl=money(plan.cost_ttl), month=money(plan.cost_month)))
    else:
        tb.add_row(t("plan.cost"), t("plan.cost_month", month=money(plan.cost_month)))
    if plan.budget_left is not None:
        tb.add_row(t("plan.budget"), t("plan.budget_v", left=money(plan.budget_left)))
    con.print(tb)


def _finish(plan: ops.Plan, res: dict[int, dict]) -> None:
    user = (plan.preset.get("vars") or {}).get("user", cloudinit.DEFAULT_VARS["user"]) if plan.user_data else "root"
    items = [{"id": i, "name": r["droplet"].get("name"), "ip": r["ip"], "state": r["state"]} for i, r in res.items()]
    if S.as_json:
        out_json({**_plan_dict(plan), "droplets": items, "generated": plan.generated})
        return
    tb = Table(t("col.name"), "IP", t("col.state"), t("col.connect"))
    for it in items:
        conn = f"ssh {user}@{it['ip']}" if it["ip"] else "-"
        if plan.preset.get("ready_port") and plan.preset.get("ready_port") != 22 and it["ip"]:
            conn = f"{it['ip']}:{plan.preset['ready_port']}  /  {conn}"
        tb.add_row(it["name"] or str(it["id"]), it["ip"] or "-", t(f"state.{it['state']}"), conn)
    con.print(tb)
    if any(it["state"] == "setup_failed" for it in items):
        con.print(f"[red]{t('up.setup_failed', user='root')}[/]")
    if plan.generated.get("password"):
        con.print(f"[bold]{t('up.password', user=user, pw=plan.generated['password'])}[/]")
    if plan.ttl_s:
        con.print(t("up.expiry_note", ttl=fleet.format_duration(plan.ttl_s)))


@app.command("ls", help="List droplets with cost so far and time left")
def ls(managed: bool = typer.Option(False, "--managed", "-m", help="Only droplets made by dofleet")):
    now = time.time()
    data = ops.rows(S.client().droplets(fleet.MARK_TAG if managed else None), now)
    if S.as_json:
        out_json(data)
        return
    if not data:
        con.print(t("ls.empty"))
        return
    tb = Table(t("col.name"), "IP", t("col.region"), t("col.size"), t("col.status"), t("col.age"),
               t("col.spent"), t("col.monthly"), t("col.expires"))
    for r in data:
        exp = "-" if r["expires_in_s"] is None else (
            f"[red]{t('ls.expired')}[/]" if r["expires_in_s"] <= 0 else fleet.format_duration(r["expires_in_s"]))
        tb.add_row(r["name"], r["ip"] or "-", r["region"], r["size"], r["status"], fleet.format_duration(r["age_s"]),
                   money(r["spent_usd"]), money(r["monthly_usd"]), exp)
    con.print(tb)
    total = sum(r["monthly_usd"] for r in data)
    con.print(t("ls.total", n=len(data), month=money(total), spent=money(sum(r["spent_usd"] for r in data))))


def _pick(patterns: list[str], any_glob: bool = True) -> list[dict]:
    hits = fleet.match(S.client().droplets(), patterns)
    if not any_glob:  # a pattern like '*' must not sweep up droplets dofleet did not make
        exact = {str(d["id"]) for d in hits} | {d["name"] for d in hits}
        named = {p for p in patterns if p in exact}
        skipped = [d for d in hits if not fleet.is_managed(d) and d["name"] not in named and str(d["id"]) not in named]
        if skipped:
            err.print(f"[yellow]{t('down.skipped', names=', '.join(d['name'] for d in skipped))}[/]")
        hits = [d for d in hits if d not in skipped]
    if not hits:
        err.print(t("err.no_match", p=" ".join(patterns)))
        raise typer.Exit(1)
    return hits


@app.command("down", help="Delete droplets by name, id or glob (web-*)")
def down(patterns: list[str] = typer.Argument(...), yes: bool = typer.Option(False, "--yes", "-y"),
         any_droplet: bool = typer.Option(False, "--any", help="Let patterns match droplets dofleet did not create"),
         missing_ok: bool = typer.Option(False, "--missing-ok", help="Exit 0 when nothing matches (already gone)")):
    if missing_ok and not fleet.match(S.client().droplets(), patterns):
        if S.as_json:
            out_json({"deleted": []})
        return
    hits = _pick(patterns, any_droplet)
    say(t("down.list", names=", ".join(d["name"] for d in hits)))
    if not confirm(t("down.confirm", n=len(hits)), yes):
        raise typer.Exit(1)
    owned = _owned_volumes(hits)
    for d in hits:
        volumes.destroy(S.client(), d, owned)
    if S.as_json:
        out_json({"deleted": [d["id"] for d in hits]})
    else:
        con.print(t("down.done", n=len(hits)))
        if any(d.get("volume_ids") for d in hits):
            con.print(t("down.volumes_async"))


@app.command("reap", help="Delete dofleet droplets whose timer ran out (safe to run from cron)")
def reap(yes: bool = typer.Option(False, "--yes", "-y"), dry_run: bool = typer.Option(False, "--dry-run")):
    now = time.time()
    victims = ops.reap_list(S.client(), S.settings, now)
    st = budget.status(S.client(), S.settings)
    if st.over:
        err.print(f"[red]{t('reap.over_budget', used=money(st.used), budget=money(st.budget))}[/]")
        if budget.action(S.settings) == "reap":
            seen = {d["id"] for d in victims}
            victims += [d for d in S.client().droplets(fleet.MARK_TAG) if d["id"] not in seen and fleet.is_managed(d)]
    orphans = ops.orphan_volumes(S.client(), now)
    if orphans:
        say(t("reap.orphans", names=", ".join(v["name"] for v in orphans)))
        if not dry_run and confirm(t("reap.orphans_confirm", n=len(orphans)), yes):
            volumes.cleanup(S.client(), [v["id"] for v in orphans])
    if S.as_json and (dry_run or not victims):
        out_json({"expired": [d["id"] for d in victims], "deleted": []})
        return
    if not victims:
        con.print(t("reap.none"))
        return
    say(t("reap.list", names=", ".join(d["name"] for d in victims)))
    if dry_run or not confirm(t("down.confirm", n=len(victims)), yes):
        return
    deleted, failed = [], []
    owned = _owned_volumes(victims)
    budget_kill = st.over and budget.action(S.settings) == "reap"
    grace = ops.reap_grace(S.settings)
    for d in victims:  # one failure must not stop the rest
        if not budget_kill and not ops.still_expired(S.client(), d, time.time(), grace):
            continue  # extended since the list was taken
        try:
            volumes.destroy(S.client(), d, owned)
            deleted.append(d)
        except ApiError as e:
            (deleted if e.status == 404 else failed).append(d)  # 404 = someone else already deleted it
    if deleted:
        _notify(t("reap.notify", n=len(deleted), names=", ".join(d["name"] for d in deleted)))
    if S.as_json:
        out_json({"expired": [d["id"] for d in victims], "deleted": [d["id"] for d in deleted],
                  "failed": [d["id"] for d in failed]})
    else:
        con.print(t("down.done", n=len(deleted)))
        if failed:
            err.print(f"[red]{t('reap.failed', names=', '.join(d['name'] for d in failed))}[/]")
    if failed:
        raise typer.Exit(1)


def _owned_volumes(droplets: list[dict]) -> set[str]:
    if not any(d.get("volume_ids") for d in droplets):
        return set()
    return {v["id"] for v in S.client().volumes() if fleet.MARK_TAG in (v.get("tags") or [])}


def _notify(message: str) -> None:
    cmd = S.settings.defaults.get("notify_cmd") or []
    if isinstance(cmd, str):
        cmd = [cmd]
    if not cmd:
        return
    import subprocess
    try:
        subprocess.run([*cmd, message], timeout=30, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        err.print(f"[yellow]{t('warn.notify', err=e)}[/]")


@app.command("extend", help="Push the expiry timer out, or remove it with --keep")
def extend(patterns: list[str] = typer.Argument(...), ttl: str = typer.Option("2h", "--ttl"),
           keep: bool = typer.Option(False, "--keep")):
    now = time.time()
    ttl_s = None if keep else fleet.parse_duration(ttl)
    done = []
    hits = _pick(patterns, any_glob=False)
    foreign = [d for d in hits if not fleet.is_managed(d)]
    if foreign:  # a timer on a droplet dofleet did not make would hand it to the reaper
        err.print(f"[yellow]{t('extend.foreign', names=', '.join(d['name'] for d in foreign))}[/]")
    for d in [d for d in hits if fleet.is_managed(d)]:
        exp = ops.set_expiry(S.client(), d, ttl_s, now)
        done.append({"id": d["id"], "name": d["name"], "expires_at": exp})
        if not S.as_json:
            con.print(t("extend.kept", name=d["name"]) if exp is None
                      else t("extend.done", name=d["name"], left=fleet.format_duration(exp - now)))
    if S.as_json:
        out_json(done)


def runjob_error():
    from .runjob import JobError
    return JobError


def main() -> None:
    from . import cli_info, cli_jobs  # noqa: F401  registers the remaining commands
    try:
        app()
    except runjob_error() as e:
        err.print(f"[red]{t(e.key, **e.kw)}[/]")
        sys.exit(1)
    except (config.ConfigError, cloudinit.TemplateError) as e:
        err.print(f"[red]{escape(t(e.key, **e.kw))}[/]")
        sys.exit(1)
    except ApiError as e:
        key = {401: "err.api_401", 403: "err.api_403", 429: "err.api_429"}.get(e.status, "err.api")
        err.print(f"[red]{escape(t(key, status=e.status, msg=e.message))}[/]")
        sys.exit(1)
    except fleet.DurationError as e:
        err.print(f"[red]{t('err.duration', text=e)}[/]")
        sys.exit(2)
