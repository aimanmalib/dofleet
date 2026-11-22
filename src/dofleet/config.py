"""Settings: bundled presets.toml merged with the user's config.toml. Code reads values; it never hard-codes them."""

from __future__ import annotations

import os
import re
import stat
import tomllib
from dataclasses import dataclass, field
from importlib import resources
from pathlib import Path

LEGACY_TOKEN_ENVS = ("DIGITALOCEAN_TOKEN", "DIGITALOCEAN_ACCESS_TOKEN", "DIGOCEAN_TOKEN")


class ConfigError(Exception):
    def __init__(self, key: str, **kw):
        super().__init__(key)
        self.key = key
        self.kw = kw


def config_dir() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or (Path.home() / ".config")
    return Path(base) / "dofleet"


def user_config_path() -> Path:
    return Path(os.environ.get("DOFLEET_CONFIG") or (config_dir() / "config.toml"))


def bundled_text(name: str) -> str:
    return resources.files("dofleet").joinpath("data", name).read_text(encoding="utf-8")


def _merge(base: dict, over: dict) -> dict:
    out = dict(base)
    for k, v in over.items():
        out[k] = _merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out


@dataclass
class Settings:
    data: dict
    path: Path
    warnings: list[str] = field(default_factory=list)

    @property
    def defaults(self) -> dict:
        return self.data.get("defaults", {})

    @property
    def presets(self) -> dict[str, dict]:
        return self.data.get("presets", {})

    def preset(self, name: str) -> dict:
        if name not in self.presets:
            raise ConfigError("err.no_preset", name=name, known=", ".join(sorted(self.presets)))
        p = dict(self.presets[name])
        for key in ("regions", "sizes"):
            if isinstance(p.get(key), str):
                p[key] = [p[key]]
            if not p.get(key):
                raise ConfigError("err.preset_field", name=name, field=key)
        p.setdefault("image", "ubuntu-24-04-x64")
        p["name"] = name
        return p

    def token(self, profile: str | None = None) -> tuple[str, str]:
        """(token, where it came from). Order: profile.token, profile.token_env, the common env names,
        then doctl's own config so people who already use doctl need no setup."""
        name = profile or os.environ.get("DOFLEET_PROFILE") or self.defaults.get("profile", "default")
        prof = self.data.get("profiles", {}).get(name)
        if prof is None:
            raise ConfigError("err.no_profile", name=name, known=", ".join(sorted(self.data.get("profiles", {}))))
        if prof.get("token"):
            return prof["token"], f"{self.path} [profiles.{name}]"
        envs = [prof["token_env"]] if prof.get("token_env") else []
        envs += [e for e in LEGACY_TOKEN_ENVS if e not in envs] if name == "default" else []
        for env in envs:
            if os.environ.get(env):
                return os.environ[env].strip(), f"${env}"
        doctl = _doctl_token(prof.get("doctl_context", "default"))
        if doctl:
            return doctl, "doctl config"
        raise ConfigError("err.no_token", profile=name, envs=", ".join(envs) or "-")


def _doctl_token(context: str) -> str | None:
    for path in (config_dir().parent / "doctl" / "config.yaml",
                 Path.home() / "Library" / "Application Support" / "doctl" / "config.yaml"):
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="replace")
        if context == "default":
            m = re.search(r"^access-token:\s*['\"]?([A-Za-z0-9_]+)", text, re.M)
        else:
            m = re.search(rf"^\s+{re.escape(context)}:\s*['\"]?([A-Za-z0-9_]+)", text, re.M)
        if m:
            return m.group(1)
    return None


def load(path: Path | None = None) -> Settings:
    path = path or user_config_path()
    data = tomllib.loads(bundled_text("presets.toml"))
    warnings: list[str] = []
    if path.is_file():
        try:
            user = tomllib.loads(path.read_text(encoding="utf-8"))
        except tomllib.TOMLDecodeError as e:
            raise ConfigError("err.bad_config", path=str(path), detail=str(e)) from e
        data = _merge(data, user)
        if _has_inline_token(user) and os.name == "posix" and path.stat().st_mode & (stat.S_IRGRP | stat.S_IROTH):
            warnings.append("warn.config_perms")
    return Settings(data, path, warnings)


def _has_inline_token(user: dict) -> bool:
    return any(isinstance(p, dict) and p.get("token") for p in user.get("profiles", {}).values())


STARTER = """# dofleet settings. Everything here overrides the bundled defaults
# (see `dofleet presets` for what is bundled). Remove a line to fall back to the default.

[defaults]
# lang = "ms"            # en | ms | auto
# preset = "quick"
# confirm_over_usd = 50

[profiles.default]
token_env = "DIGITALOCEAN_TOKEN"
# token = "dop_v1_..."   # works, but an env var keeps the secret out of this file

# [profiles.client-a]
# token_env = "CLIENT_A_DO_TOKEN"

# [presets.quick]
# regions = ["sgp1"]
# ttl = "4h"

# [presets.my-worker]
# description = "My own preset"
# regions = ["sgp1", "blr1"]
# sizes = ["s-2vcpu-4gb"]
# image = "ubuntu-24-04-x64"
# cloud_init = "docker"          # bundled template name, or a path to your own cloud-init file
# ttl = "12h"
# tags = ["worker"]
# vars = { user = "ops" }
"""


def write_starter(path: Path | None = None) -> Path:
    path = path or user_config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise ConfigError("err.config_exists", path=str(path))
    path.write_text(STARTER, encoding="utf-8")
    if os.name == "posix":
        path.chmod(0o600)
    return path
