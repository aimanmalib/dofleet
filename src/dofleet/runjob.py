"""`dofleet run`: one job on a fresh droplet, then the droplet is gone.

create -> wait for setup -> copy a local folder up -> run the command (output streams live) -> copy results back
-> delete droplet and its volumes. The droplet's expiry timer stays on as a backstop: if this process dies half way,
`reap` still deletes it. Files go over plain ssh + tar, so nothing beyond OpenSSH and tar is needed on either side."""

from __future__ import annotations

import shlex
import subprocess
from pathlib import Path

from . import ready

WORKDIR = "work"  # relative to the login user's home on the droplet


class JobError(Exception):
    def __init__(self, key: str, **kw):
        super().__init__(key)
        self.key = key
        self.kw = kw


def _ssh(droplet_id: int, ip: str, user: str, identity: str | None) -> list[str]:
    return ["ssh", *ready.ssh_args(droplet_id, identity), f"{user}@{ip}"]


def _pipe(producer: list[str], consumer: list[str], step: str) -> None:
    """producer | consumer, both without a shell; fail loudly if either side fails."""
    p1 = subprocess.Popen(producer, stdout=subprocess.PIPE)
    p2 = subprocess.Popen(consumer, stdin=p1.stdout)
    p1.stdout.close()
    rc2 = p2.wait()
    rc1 = p1.wait()
    if rc1 or rc2:
        raise JobError("err.run_copy", step=step, rc=rc1 or rc2)


def upload(droplet_id: int, ip: str, user: str, identity: str | None, folder: Path) -> None:
    if not folder.is_dir():
        raise JobError("err.run_no_folder", path=str(folder))
    _pipe(["tar", "czf", "-", "-C", str(folder), "."],
          [*_ssh(droplet_id, ip, user, identity), f"mkdir -p {WORKDIR} && tar xzf - -C {WORKDIR}"], "upload")


def execute(droplet_id: int, ip: str, user: str, identity: str | None, command: list[str],
            env: dict[str, str] | None = None) -> int:
    exports = " ".join(f"{k}={shlex.quote(v)}" for k, v in (env or {}).items())
    remote = f"mkdir -p {WORKDIR} && cd {WORKDIR} && {('env ' + exports + ' ') if exports else ''}{shlex.join(command)}"
    return subprocess.call([*_ssh(droplet_id, ip, user, identity), remote])


def download(droplet_id: int, ip: str, user: str, identity: str | None, paths: list[str], dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    quoted = " ".join(shlex.quote(p) for p in paths)
    _pipe([*_ssh(droplet_id, ip, user, identity), f"cd {WORKDIR} && tar czf - -- {quoted}"],
          ["tar", "xzf", "-", "-C", str(dest)], "download")
