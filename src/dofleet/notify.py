"""Build the argv for the operator's ``notify_cmd``.

Standard library only and no imports from the ``dofleet`` package: host checks load this file on its own.

``notify_cmd`` may contain ``{message}`` and ``{level}`` in any argument. Without ``{message}`` anywhere the
message is appended as the last argument (the form configs used before levels existed).
Substitution is plain replacement of those two tokens, so braces in droplet names pass through untouched.
"""

from __future__ import annotations

LEVELS = ("info", "warn", "critical")
MESSAGE, LEVEL = "{message}", "{level}"


def _fill(arg: str, message: str, level: str) -> str:
    # Split on {message} first so a {level} inside the message itself is never replaced.
    return message.join(part.replace(LEVEL, level) for part in arg.split(MESSAGE))


def build_argv(cmd: list[str] | str | None, message: str, level: str) -> list[str]:
    if level not in LEVELS:
        raise ValueError(f"unknown notify level: {level!r} (expected one of {', '.join(LEVELS)})")
    if isinstance(cmd, str):
        cmd = [cmd]
    cmd = [str(a) for a in (cmd or [])]
    if not cmd:
        return []
    if not any(MESSAGE in a for a in cmd):
        return [*(a.replace(LEVEL, level) for a in cmd), message]
    return [_fill(a, message, level) for a in cmd]
