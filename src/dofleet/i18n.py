"""Every user-facing string lives in locales/<lang>.json. Code only holds keys."""

from __future__ import annotations

import json
import os
from functools import lru_cache
from importlib import resources

SUPPORTED = ("en", "ms")
_lang = "en"


@lru_cache(maxsize=None)
def _table(lang: str) -> dict[str, str]:
    return json.loads(resources.files("dofleet").joinpath("locales", f"{lang}.json").read_text(encoding="utf-8"))


def resolve(explicit: str | None = None, configured: str | None = None) -> str:
    for cand in (explicit, os.environ.get("DOFLEET_LANG"), configured):
        if cand and cand != "auto":
            return cand if cand in SUPPORTED else "en"
    sys_lang = (os.environ.get("LC_ALL") or os.environ.get("LC_MESSAGES") or os.environ.get("LANG") or "").lower()
    return "ms" if sys_lang.startswith(("ms", "my_")) else "en"


def set_lang(lang: str) -> None:
    global _lang
    _lang = lang if lang in SUPPORTED else "en"


def lang() -> str:
    return _lang


def t(key: str, **kw) -> str:
    text = _table(_lang).get(key) or _table("en").get(key) or key
    try:
        return text.format(**kw)
    except (KeyError, IndexError):
        return text
