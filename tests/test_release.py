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
