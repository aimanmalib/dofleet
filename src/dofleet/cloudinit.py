"""Build user_data from a bundled template name or a path to the user's own file.

Templates are shell scripts. `#include <name>` pulls another template in (once), so "docker" = "harden" + docker.
Placeholders use ${name}; unknown ones are left as they are, so normal shell `$VAR` keeps working."""

from __future__ import annotations

import re
import secrets
import string
from importlib import resources
from pathlib import Path

DEFAULT_VARS = {"user": "ops", "password_auth": "no", "rdp_port": "3389"}
USER_DATA_LIMIT = 64 * 1024  # DigitalOcean rejects user_data over 64 KiB
_INCLUDE = re.compile(r"^#include\s+(\S+)\s*$", re.M)
_SAFE_VALUE = re.compile(r"^[A-Za-z0-9._@:/+=-]*$")


class TemplateError(Exception):
    def __init__(self, key: str, **kw):
        super().__init__(key)
        self.key = key
        self.kw = kw


def bundled_names() -> list[str]:
    folder = resources.files("dofleet").joinpath("data", "templates")
    return sorted(p.name[:-3] for p in folder.iterdir() if p.name.endswith(".sh"))


def describe(name: str) -> str:
    for line in _read(name).splitlines()[2:4]:
        if line.startswith("# ") and not line.startswith("# Vars"):
            return line[2:]
    return ""


def _read(name: str) -> str:
    if name in bundled_names():
        return resources.files("dofleet").joinpath("data", "templates", f"{name}.sh").read_text(encoding="utf-8")
    path = Path(name).expanduser()
    if path.is_file():
        return path.read_text(encoding="utf-8")
    raise TemplateError("err.no_template", name=name, known=", ".join(bundled_names()))


def _expand(name: str, seen: set[str]) -> str:
    if name in seen:
        return ""
    seen.add(name)
    text = _read(name)

    def inline(m: re.Match) -> str:
        body = _expand(m.group(1), seen)
        return "\n".join(line for line in body.splitlines()
                         if not line.startswith("#!") and not line.startswith("# dofleet template"))
    return _INCLUDE.sub(inline, text)


def render(name: str | None, given: dict | None = None) -> tuple[str | None, dict[str, str]]:
    """Returns (user_data or None, values that were generated and must be shown to the user once)."""
    if not name:
        return None, {}
    text = _expand(name, set())
    values = {**DEFAULT_VARS, **{k: str(v) for k, v in (given or {}).items()}}
    generated: dict[str, str] = {}
    if "${password}" in text and not values.get("password"):
        alphabet = string.ascii_letters + string.digits
        values["password"] = generated["password"] = "".join(secrets.choice(alphabet) for _ in range(20))
    for key, value in values.items():
        if not _SAFE_VALUE.match(value):
            raise TemplateError("err.bad_var", name=key)
    out = string.Template(text).safe_substitute(values)
    if len(out.encode()) > USER_DATA_LIMIT:
        raise TemplateError("err.user_data_size", size=len(out.encode()))
    return out, generated
