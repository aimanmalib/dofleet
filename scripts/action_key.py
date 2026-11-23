"""The GitHub Action's runner key on the DigitalOcean account: find it before a step, remove it after.

A fresh runner key is uploaded so dofleet can reach the droplet. Once the droplet exists the account copy is no longer
needed (the key is already inside the droplet), and without this every CI run would leave one more SSH key on the
account. Only a key this step added is removed: `find` runs first and prints the key id, nothing (not on the account),
or "?" (could not tell); `forget` acts only after an empty `find`, and only on keys dofleet named `dofleet-*`.
Standard library only, so it runs whatever Python the runner has.

    python3 action_key.py find KEY.pub
    python3 action_key.py forget KEY.pub BEFORE
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request

API = "https://api.digitalocean.com/v2"


def fingerprint(public_key: str) -> str:
    """MD5 fingerprint in DigitalOcean's aa:bb:.. form (same as dofleet.ops.key_fingerprint)."""
    digest = hashlib.md5(base64.b64decode(public_key.split()[1]), usedforsecurity=False).hexdigest()
    return ":".join(digest[i:i + 2] for i in range(0, 32, 2))


def http_caller(token: str):
    def call(method: str, path: str):
        req = urllib.request.Request(API + path, method=method, headers={
            "Authorization": "Bearer " + token, "Content-Type": "application/json", "User-Agent": "dofleet-action"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e:
            return e.code, {}
    return call


def find(call, public_key: str) -> str:
    try:
        status, body = call("GET", f"/account/keys/{fingerprint(public_key)}")
    except (OSError, ValueError):
        return "?"
    if status == 404:
        return ""
    return str((body.get("ssh_key") or {}).get("id") or "?") if status == 200 else "?"


def forget(call, public_key: str, before: str) -> str | None:
    """Remove the key when it was not on the account before this step and dofleet added it. Returns its name."""
    if before != "":
        return None
    try:
        status, body = call("GET", f"/account/keys/{fingerprint(public_key)}")
        key = body.get("ssh_key") or {}
        if status != 200 or not str(key.get("name", "")).startswith("dofleet-"):
            return None
        status, _ = call("DELETE", f"/account/keys/{key['id']}")
    except (OSError, ValueError, KeyError):
        return None
    return key["name"] if status in (204, 404) else None


def main(argv: list[str]) -> int:
    token = os.environ.get("DIGITALOCEAN_TOKEN", "")
    if len(argv) < 2 or not token:
        return 0  # housekeeping only: never fail the step
    try:
        public_key = open(argv[1], encoding="utf-8").read()
    except OSError:
        print("?" if argv[0] == "find" else "", end="")
        return 0
    call = http_caller(token)
    if argv[0] == "find":
        print(find(call, public_key), end="")
    elif argv[0] == "forget" and len(argv) > 2:
        name = forget(call, public_key, argv[2])
        if name:
            print(f"dofleet: removed the runner key {name} from the account (the droplet keeps it)", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
