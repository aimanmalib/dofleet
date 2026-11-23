"""The version lives in four places. A release that misses one ships a wrong `dofleet --version` or MCP Registry entry."""

import json
import pathlib
import tomllib

from dofleet import __version__

ROOT = pathlib.Path(__file__).resolve().parents[1]


def test_versions_agree():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())["project"]["version"]
    server = json.loads((ROOT / "server.json").read_text())
    assert __version__ == project == server["version"] == server["packages"][0]["version"]


def test_action_metadata_has_no_expressions_outside_defaults_and_runs():
    """GitHub refuses to load an action whose input description holds ${{ ... }} (measured 23 Nov 2026: "Unrecognized
    named-value: 'github'", the whole action failed for every user). Defaults and the runs section may use them."""
    section, bad = None, []
    for n, line in enumerate((ROOT / "action.yml").read_text().splitlines(), 1):
        if line and not line.startswith(" "):
            section = line.split(":")[0]
        key = line.strip().split(":")[0]
        if "${{" in line and section in ("name", "description", "author", "inputs") and key != "default":
            bad.append(f"{n}: {line.strip()}")
    assert not bad, bad
