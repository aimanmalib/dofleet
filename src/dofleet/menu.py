"""Numbered menu for people who would rather not remember commands. Every entry calls the same code as the CLI."""

from __future__ import annotations

import typer

from .i18n import t

ENTRIES = ("menu.up", "menu.ls", "menu.extend", "menu.down", "menu.reap", "menu.cost", "menu.sizes", "menu.quit")


def run_menu(cli) -> None:
    while True:
        cli.con.rule("dofleet")
        for i, key in enumerate(ENTRIES, 1):
            cli.con.print(f"  {i}. {t(key)}")
        choice = typer.prompt(t("menu.pick"), default="2").strip()
        if choice in ("8", "q", ""):
            return
        try:
            _run(cli, choice)
        except typer.Exit:
            pass
        except typer.Abort:
            cli.con.print()


def _run(cli, choice: str) -> None:
    from . import cli_info as info
    if choice == "1":
        info.presets()
        preset = typer.prompt(t("menu.which_preset"), default=cli.S.settings.defaults.get("preset", "quick"))
        name = typer.prompt(t("menu.name"), default=preset)
        count = typer.prompt(t("menu.count"), default=1, type=int)
        ttl = typer.prompt(t("menu.ttl"), default=cli.S.settings.presets.get(preset, {}).get("ttl") or "")
        cli.up(preset=preset, name=name, count=count, ttl=ttl, keep=not ttl, region=[], size=[], image=None,
               tag=[], var=[], volume=[], baked=False, yes=False, dry_run=False, no_wait=False)
    elif choice == "2":
        cli.ls(managed=False)
    elif choice == "3":
        cli.ls(managed=True)
        target = typer.prompt(t("menu.target"))
        cli.extend(patterns=[target], ttl=typer.prompt(t("menu.ttl"), default="2h"), keep=False)
    elif choice == "4":
        cli.ls(managed=False)
        cli.down(patterns=typer.prompt(t("menu.target")).split(), yes=False, any_droplet=False, missing_ok=False)
    elif choice == "5":
        cli.reap(yes=False, dry_run=False)
    elif choice == "6":
        info.cost()
    elif choice == "7":
        info.sizes(region=typer.prompt(t("menu.region"), default="sgp1"), family="basic")
