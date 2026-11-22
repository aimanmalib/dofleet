"""dofleet reaper, running as a DigitalOcean Function on a schedule (installed by `dofleet install-reaper`).

Standalone on purpose: the Functions runtime has only the standard library. Rules match `dofleet reap`:
- droplets tagged `dofleet` whose `dofleet-exp-<unix time>` (+ grace) has passed are deleted with their dofleet volumes;
- when month-to-date usage has reached `budget_usd` and budget_action is "reap", every dofleet droplet is deleted;
- dofleet volumes attached to nothing for over an hour are deleted ("since when" = a dofleet-detached-<time> tag
  set the first time a run sees the volume detached, so a volume someone just moved by hand is not lost).
Parameters (set at install): token, grace_s, budget_usd, budget_action, notify_url, dry_run."""

import json
import time
import urllib.error
import urllib.request
from datetime import datetime

API = "https://api.digitalocean.com/v2"
MARK = "dofleet"
EXP = "dofleet-exp-"
DETACHED = "dofleet-detached-"


def http_caller(token):
    def call(method, path, body=None, params=""):
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(API + path + params, data=data, method=method, headers={
            "Authorization": "Bearer " + token, "Content-Type": "application/json", "User-Agent": "dofleet-reaper"})
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                raw = resp.read()
                return resp.status, (json.loads(raw) if raw else {})
        except urllib.error.HTTPError as e:
            return e.code, {}
    return call


def all_pages(call, path, key, query=""):
    items, page = [], 1
    while True:
        status, data = call("GET", path, params=f"?per_page=200&page={page}{query}")
        if status != 200:
            raise RuntimeError(f"GET {path} -> {status}")
        items += data.get(key) or []
        if not ((data.get("links") or {}).get("pages") or {}).get("next"):
            return items
        page += 1


def stamp(text):
    try:
        return datetime.fromisoformat((text or "").replace("Z", "+00:00")).timestamp()
    except ValueError:
        return time.time()


def expiry(droplet):
    found = [int(t[len(EXP):]) for t in droplet.get("tags") or [] if t.startswith(EXP) and t[len(EXP):].isdigit()]
    return min(found) if found else None


def reap(call, now, grace_s=0, budget_usd=0.0, budget_action="reap", dry_run=False):
    mine = [d for d in all_pages(call, "/droplets", "droplets", f"&tag_name={MARK}") if MARK in (d.get("tags") or [])]
    over = False
    if budget_usd > 0:
        _, bal = call("GET", "/customers/my/balance")
        over = float(bal.get("month_to_date_usage") or 0) >= budget_usd
    doomed = [d for d in mine if (over and budget_action == "reap")
              or (expiry(d) is not None and expiry(d) + grace_s <= now)]
    vols = [v for v in all_pages(call, "/volumes", "volumes") if MARK in (v.get("tags") or [])]
    owned = {v["id"] for v in vols}
    done, failed = [], []
    budget_kill = over and budget_action == "reap"
    for d in doomed:
        if dry_run:
            done.append(d["name"])
            continue
        if not budget_kill:  # re-read: it may have been extended since the list was taken
            status, fresh = call("GET", f"/droplets/{d['id']}")
            fresh = fresh.get("droplet") or {}
            if status != 200 or expiry(fresh) is None or expiry(fresh) + grace_s > now:
                continue
        attached = [v for v in d.get("volume_ids") or [] if v in owned]
        if attached:
            status, _ = call("DELETE", f"/droplets/{d['id']}/destroy_with_associated_resources/selective",
                             {"volumes": attached})
        else:
            status, _ = call("DELETE", f"/droplets/{d['id']}")
        if status in (202, 204, 404):
            done.append(d["name"])
        elif status != 422:  # 422 = already being deleted (by the other reaper)
            failed.append(d["name"])
    orphans = []
    for v in vols:
        marks = [int(t[len(DETACHED):]) for t in v.get("tags") or [] if t.startswith(DETACHED) and t[len(DETACHED):].isdigit()]
        if v.get("droplet_ids"):
            for t in v.get("tags") or []:
                if t.startswith(DETACHED) and not dry_run:
                    call("DELETE", f"/tags/{t}/resources", {"resources": [{"resource_id": v["id"], "resource_type": "volume"}]})
        elif not marks:
            if not dry_run and now - stamp(v.get("created_at")) > 300:
                tag = f"{DETACHED}{int(now)}"
                call("POST", "/tags", {"name": tag})
                call("POST", f"/tags/{tag}/resources", {"resources": [{"resource_id": v["id"], "resource_type": "volume"}]})
        elif now - min(marks) > 3600:
            orphans.append(v)
    for v in orphans:
        if not dry_run:
            call("DELETE", f"/volumes/{v['id']}")
    return {"deleted": done, "failed": failed, "orphan_volumes": [v["name"] for v in orphans],
            "over_budget": over, "checked": len(mine), "dry_run": dry_run}


def notify(url, result):
    if not url or not (result["deleted"] or result["failed"] or result["orphan_volumes"]):
        return
    text = (f"dofleet reaper: deleted {len(result['deleted'])} droplet(s) {', '.join(result['deleted'])}"
            + (f"; FAILED {', '.join(result['failed'])}" if result["failed"] else "")
            + (f"; orphan volumes {', '.join(result['orphan_volumes'])}" if result["orphan_volumes"] else "")
            + ("; month budget reached" if result["over_budget"] else ""))
    req = urllib.request.Request(url, data=json.dumps({"text": text, "content": text}).encode(),
                                 headers={"Content-Type": "application/json"}, method="POST")
    try:
        urllib.request.urlopen(req, timeout=15).read()
    except (urllib.error.URLError, OSError):
        pass


def main(args):
    result = reap(http_caller(args["token"]), time.time(), int(args.get("grace_s") or 0),
                  float(args.get("budget_usd") or 0), str(args.get("budget_action") or "reap"),
                  bool(args.get("dry_run")))
    notify(args.get("notify_url"), result)
    return {"body": result}
