"""Thin DigitalOcean API v2 client: pagination, retries on 429/5xx, readable errors."""

from __future__ import annotations

import time
from typing import Any, Iterator

import httpx

API_BASE = "https://api.digitalocean.com/v2"
RETRY_STATUS = {429, 500, 502, 503, 504}


class ApiError(Exception):
    def __init__(self, status: int, message: str, error_id: str = ""):
        super().__init__(f"HTTP {status}: {message}")
        self.status = status
        self.message = message
        self.error_id = error_id


class DOClient:
    def __init__(self, token: str, *, base: str = API_BASE, transport: httpx.BaseTransport | None = None,
                 retries: int = 4, sleep=time.sleep):
        self._http = httpx.Client(
            base_url=base,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json",
                     "User-Agent": "dofleet"},
            timeout=30,
            transport=transport,
        )
        self._retries = retries
        self._sleep = sleep

    def close(self) -> None:
        self._http.close()

    # ---- low level -------------------------------------------------------
    def request(self, method: str, path: str, **kw) -> dict[str, Any]:
        for attempt in range(self._retries + 1):
            resp = self._http.request(method, path, **kw)
            # A POST that got a 5xx may still have created droplets; only 429 (not processed) is safe to resend.
            retryable = RETRY_STATUS if method.upper() in ("GET", "DELETE") else {429}
            if resp.status_code in retryable and attempt < self._retries:
                self._sleep(self._retry_delay(resp, attempt))
                continue
            break
        if resp.status_code >= 400:
            try:
                body = resp.json()
            except ValueError:
                body = {}
            raise ApiError(resp.status_code, body.get("message") or resp.reason_phrase, body.get("id", ""))
        if resp.status_code == 204 or not resp.content:
            return {}
        return resp.json()

    @staticmethod
    def _retry_delay(resp: httpx.Response, attempt: int) -> float:
        reset = resp.headers.get("ratelimit-reset")
        if resp.status_code == 429 and reset and reset.isdigit():
            return max(1.0, min(60.0, int(reset) - time.time()))
        return min(30.0, 2.0 ** attempt)

    def paginate(self, path: str, key: str, params: dict | None = None) -> Iterator[dict]:
        params = {"per_page": 200, **(params or {})}
        page = 1
        while True:
            data = self.request("GET", path, params={**params, "page": page})
            yield from data.get(key, [])
            if not (data.get("links") or {}).get("pages", {}).get("next"):
                return
            page += 1

    # ---- resources -------------------------------------------------------
    def account(self) -> dict:
        return self.request("GET", "/account").get("account", {})

    def balance(self) -> dict:
        return self.request("GET", "/customers/my/balance")

    def sizes(self) -> list[dict]:
        return list(self.paginate("/sizes", "sizes"))

    def regions(self) -> list[dict]:
        return list(self.paginate("/regions", "regions"))

    def ssh_keys(self) -> list[dict]:
        return list(self.paginate("/account/keys", "ssh_keys"))

    def create_ssh_key(self, name: str, public_key: str) -> dict:
        return self.request("POST", "/account/keys", json={"name": name, "public_key": public_key}).get("ssh_key", {})

    def delete_ssh_key(self, key_id: int) -> None:
        self.request("DELETE", f"/account/keys/{key_id}")

    def droplets(self, tag: str | None = None) -> list[dict]:
        return list(self.paginate("/droplets", "droplets", {"tag_name": tag} if tag else None))

    def droplet(self, droplet_id: int) -> dict:
        return self.request("GET", f"/droplets/{droplet_id}").get("droplet", {})

    def create_droplets(self, body: dict) -> list[dict]:
        data = self.request("POST", "/droplets", json=body)
        if "droplets" in data:
            return data["droplets"]
        return [data["droplet"]] if "droplet" in data else []

    def delete_droplet(self, droplet_id: int) -> None:
        self.request("DELETE", f"/droplets/{droplet_id}")

    def volumes(self) -> list[dict]:
        return list(self.paginate("/volumes", "volumes"))

    def create_volume(self, name: str, region: str, size_gb: int, tags: list[str]) -> dict:
        return self.request("POST", "/volumes", json={"name": name, "region": region, "size_gigabytes": size_gb,
                                                       "tags": tags, "filesystem_type": "ext4"}).get("volume", {})

    def delete_volume(self, volume_id: str) -> None:
        self.request("DELETE", f"/volumes/{volume_id}")

    def destroy_with_volumes(self, droplet_id: int, volume_ids: list[str]) -> None:
        """Delete the droplet and exactly these attached volumes in one call (snapshots/backups untouched)."""
        self.request("DELETE", f"/droplets/{droplet_id}/destroy_with_associated_resources/selective",
                     json={"volumes": volume_ids})

    def droplet_action(self, droplet_id: int, action: str) -> dict:
        return self.request("POST", f"/droplets/{droplet_id}/actions", json={"type": action}).get("action", {})

    def tag_resource(self, tag: str, droplet_id, kind: str = "droplet") -> None:
        try:
            self.request("POST", "/tags", json={"name": tag})
        except ApiError as e:
            if e.status != 422:  # 422 = tag already exists, which is fine
                raise
        self.request("POST", f"/tags/{tag}/resources",
                     json={"resources": [{"resource_id": str(droplet_id), "resource_type": kind}]})

    def untag_resource(self, tag: str, droplet_id, kind: str = "droplet") -> None:
        self.request("DELETE", f"/tags/{tag}/resources",
                     json={"resources": [{"resource_id": str(droplet_id), "resource_type": kind}]})

    def tags(self) -> list[dict]:
        return list(self.paginate("/tags", "tags"))

    def delete_tag(self, tag: str) -> None:
        """Deleting a tag also strips it from every resource that still carries it: callers check it is empty first."""
        self.request("DELETE", f"/tags/{tag}")


def public_ipv4(droplet: dict) -> str | None:
    for net in (droplet.get("networks") or {}).get("v4", []):
        if net.get("type") == "public":
            return net.get("ip_address")
    return None
