"""In-memory stand-in for the parts of the DigitalOcean API dofleet uses."""

from __future__ import annotations

import json
import re

import httpx

SIZES = [
    {"slug": "s-1vcpu-1gb", "vcpus": 1, "memory": 1024, "disk": 25, "price_monthly": 6.0, "price_hourly": 0.00893,
     "regions": ["sgp1", "blr1"], "available": True},
    {"slug": "s-4vcpu-8gb", "vcpus": 4, "memory": 8192, "disk": 160, "price_monthly": 48.0, "price_hourly": 0.07143,
     "regions": ["blr1"], "available": True},
    {"slug": "s-4vcpu-8gb-amd", "vcpus": 4, "memory": 8192, "disk": 160, "price_monthly": 56.0, "price_hourly": 0.08333,
     "regions": ["sgp1", "blr1"], "available": True},
]
REGIONS = [
    {"slug": "sgp1", "available": True, "sizes": ["s-1vcpu-1gb", "s-4vcpu-8gb-amd"]},
    {"slug": "blr1", "available": True, "sizes": ["s-1vcpu-1gb", "s-4vcpu-8gb", "s-4vcpu-8gb-amd"]},
]


class FakeDO:
    def __init__(self):
        self.droplets: dict[int, dict] = {}
        self.keys = [{"id": 11, "name": "laptop", "fingerprint": "aa:bb"}]
        self.created_bodies: list[dict] = []
        self.sold_out: set[tuple[str, str]] = set()
        self.calls: list[tuple[str, str]] = []
        self.fail_next: list[int] = []
        self.next_id = 1000
        self.delete_errors: dict[int, int] = {}
        self.vols: dict[str, dict] = {}
        self.usage = "12.50"
        self.snaps: list[dict] = []
        self.namespaces: list[dict] = []
        self.triggers: list[dict] = []
        self.page_size = 2  # force pagination in tests

    def add(self, name, tags=(), created="2026-01-01T00:00:00Z", size=SIZES[0], status="active", ip="203.0.113.5"):
        self.next_id += 1
        d = {"id": self.next_id, "name": name, "status": status, "created_at": created, "tags": list(tags),
             "size_slug": size["slug"], "size": size, "region": {"slug": "sgp1"},
             "networks": {"v4": [{"type": "public", "ip_address": ip}] if ip else []}}
        self.droplets[d["id"]] = d
        return d

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def _page(self, req, key, items):
        page = int(req.url.params.get("page", 1))
        chunk = items[(page - 1) * self.page_size: page * self.page_size]
        more = page * self.page_size < len(items)
        return {key: chunk, "links": {"pages": {"next": "x"} if more else {}}, "meta": {"total": len(items)}}

    def handle(self, req: httpx.Request) -> httpx.Response:
        path, m = req.url.path.removeprefix("/v2"), req.method
        self.calls.append((m, path))
        if self.fail_next:
            return httpx.Response(self.fail_next.pop(0), json={"id": "x", "message": "boom"})
        body = json.loads(req.content) if req.content else {}
        if m == "GET" and path == "/sizes":
            return httpx.Response(200, json=self._page(req, "sizes", SIZES))
        if m == "GET" and path == "/regions":
            return httpx.Response(200, json=self._page(req, "regions", REGIONS))
        if m == "GET" and path == "/account/keys":
            return httpx.Response(200, json=self._page(req, "ssh_keys", self.keys))
        if m == "GET" and (mm := re.fullmatch(r"/account/keys/([0-9a-f:]+)", path)):
            hit = [k for k in self.keys if k["fingerprint"] == mm.group(1)]
            return httpx.Response(200, json={"ssh_key": hit[0]}) if hit else httpx.Response(404, json={"message": "nf"})
        if m == "POST" and path == "/account/keys":
            from dofleet.ops import key_fingerprint
            k = {"id": 99, "name": body["name"], "fingerprint": key_fingerprint(body["public_key"]),
                 "public_key": body["public_key"]}
            self.keys.append(k)
            return httpx.Response(201, json={"ssh_key": k})
        if m == "GET" and path == "/account":
            return httpx.Response(200, json={"account": {"email": "a@example.com", "status": "active", "droplet_limit": 10}})
        if m == "GET" and path == "/customers/my/balance":
            return httpx.Response(200, json={"month_to_date_balance": self.usage, "account_balance": "0.00",
                                             "month_to_date_usage": self.usage})
        if m == "GET" and path == "/snapshots":
            return httpx.Response(200, json=self._page(req, "snapshots", self.snaps))
        if m == "DELETE" and (mm := re.fullmatch(r"/snapshots/(\d+)", path)):
            self.snaps = [x for x in self.snaps if str(x["id"]) != mm.group(1)]
            return httpx.Response(204)
        if m == "GET" and (mm := re.fullmatch(r"/actions/(\d+)", path)):
            return httpx.Response(200, json={"action": {"id": int(mm.group(1)), "status": "completed"}})
        if path == "/functions/namespaces":
            if m == "GET":
                return httpx.Response(200, json={"namespaces": [{k: v for k, v in n.items() if k != "key"}
                                                                for n in self.namespaces] or None})
            if any(n["label"] == body["label"] for n in self.namespaces):  # measured: DO rejects duplicate labels
                return httpx.Response(422, json={"message": f"label '{body['label']}' already in use"})
            ns = {"namespace": f"fn-{len(self.namespaces) + 1}", "label": body["label"], "region": body["region"],
                  "api_host": "https://faas.test", "uuid": "u", "key": "k"}
            self.namespaces.append(ns)
            return httpx.Response(200, json={"namespace": ns})
        if mm := re.fullmatch(r"/functions/namespaces/([^/]+)", path):
            self.namespaces = [n for n in self.namespaces if n["namespace"] != mm.group(1)]
            return httpx.Response(204)
        if mm := re.fullmatch(r"/functions/namespaces/([^/]+)/triggers", path):
            self.triggers.append(body)
            return httpx.Response(200, json={"trigger": body})
        if m == "GET" and path == "/droplets":
            tag = req.url.params.get("tag_name")
            items = [d for d in self.droplets.values() if not tag or tag in d["tags"]]
            return httpx.Response(200, json=self._page(req, "droplets", items))
        if m == "GET" and path == "/volumes":
            return httpx.Response(200, json=self._page(req, "volumes", list(self.vols.values())))
        if m == "POST" and path == "/volumes":
            vid = f"vol-{len(self.vols) + 1}"
            self.vols[vid] = {"id": vid, "name": body["name"], "region": body["region"],
                              "size_gigabytes": body["size_gigabytes"], "tags": body.get("tags", [])}
            return httpx.Response(201, json={"volume": self.vols[vid]})
        if mm := re.fullmatch(r"/volumes/([^/]+)", path):
            self.vols.pop(mm.group(1), None)
            return httpx.Response(204)
        if mm := re.fullmatch(r"/droplets/(\d+)/destroy_with_associated_resources/selective", path):
            self.droplets.pop(int(mm.group(1)))
            for v in body.get("volumes", []):
                self.vols.pop(v, None)
            return httpx.Response(202)
        if m == "POST" and path == "/droplets":
            self.created_bodies.append(body)
            if (body["region"], body["size"]) in self.sold_out:
                return httpx.Response(422, json={"id": "unprocessable_entity",
                                                 "message": "Size is not available in this region."})
            size = next(s for s in SIZES if s["slug"] == body["size"])
            made = [self.add(n, body.get("tags", []), size=size, status="new", ip=None) for n in body["names"]]
            for d in made:
                d["volume_ids"] = list(body.get("volumes", []))
            return httpx.Response(202, json={"droplets": made})
        if mm := re.fullmatch(r"/droplets/(\d+)", path):
            did = int(mm.group(1))
            if m == "DELETE" and did in self.delete_errors:
                return httpx.Response(self.delete_errors[did], json={"id": "x", "message": "nope"})
            if did not in self.droplets:
                return httpx.Response(404, json={"id": "not_found", "message": "not found"})
            if m == "DELETE":
                del self.droplets[did]
                return httpx.Response(204)
            d = self.droplets[did]
            d["status"], d["networks"] = "active", {"v4": [{"type": "public", "ip_address": f"198.51.100.{did % 250}"}]}
            return httpx.Response(200, json={"droplet": d})
        if m == "POST" and (mm := re.fullmatch(r"/droplets/(\d+)/actions", path)):
            if body["type"] == "snapshot":
                d = self.droplets[int(mm.group(1))]
                self.snaps.append({"id": 500 + len(self.snaps), "name": body["name"], "regions": ["sgp1"],
                                   "size_gigabytes": 2, "resource_id": d["id"]})
                return httpx.Response(201, json={"action": {"id": 77, "status": "in-progress"}})
            return httpx.Response(201, json={"action": {"type": body["type"], "status": "in-progress"}})
        if m == "POST" and path == "/tags":
            return httpx.Response(201, json={"tag": {"name": body["name"]}})
        if mm := re.fullmatch(r"/tags/([^/]+)/resources", path):
            for r in body["resources"]:
                if r.get("resource_type") == "volume":
                    tags = self.vols[r["resource_id"]].setdefault("tags", [])
                else:
                    tags = self.droplets[int(r["resource_id"])]["tags"]
                if m == "POST" and mm.group(1) not in tags:
                    tags.append(mm.group(1))
                if m == "DELETE" and mm.group(1) in tags:
                    tags.remove(mm.group(1))
            return httpx.Response(204)
        return httpx.Response(404, json={"id": "not_found", "message": f"no route {m} {path}"})
