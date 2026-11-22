"""Pick a (region, size) pair that is actually in stock, walking the preset's fallback chains."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass
class Choice:
    region: str
    size: dict
    fell_back: bool


def in_stock(sizes: list[dict], regions: list[dict]) -> dict[str, set[str]]:
    """region slug -> set of size slugs available right now (both views must agree)."""
    size_ok = {s["slug"]: set(s.get("regions", [])) for s in sizes if s.get("available", True)}
    out: dict[str, set[str]] = {}
    for r in regions:
        if not r.get("available", True):
            continue
        listed = set(r.get("sizes", []))
        out[r["slug"]] = {slug for slug in listed if r["slug"] in size_ok.get(slug, set())}
    return out


def choose(region_chain: list[str], size_chain: list[str], sizes: list[dict], regions: list[dict],
           skip: set[tuple[str, str]] | None = None) -> Choice | None:
    """First pair in stock. Region order wins over size order: a user who asks for Singapore would rather
    get the AMD twin in Singapore than the basic size in Bangalore."""
    stock = in_stock(sizes, regions)
    by_slug = {s["slug"]: s for s in sizes}
    skip = skip or set()
    first = (region_chain[0], size_chain[0]) if region_chain and size_chain else None
    for region in region_chain:
        for slug in size_chain:
            if (region, slug) in skip:
                continue
            if slug in stock.get(region, set()) and slug in by_slug:
                return Choice(region, by_slug[slug], (region, slug) != first)
    return None


def filter_sizes(sizes: list[dict], region: str | None = None, family: str = "all") -> list[dict]:
    """family: basic | premium | cpu | memory | gpu | all. Sorted by monthly price, then slug (stable numbering)."""
    def fam(slug: str) -> str:
        if slug.startswith("gpu-"):
            return "gpu"
        if slug.startswith(("c-", "c2-")):
            return "cpu"
        if slug.startswith(("m-", "m3-", "m6-", "so-", "so1_5-", "g-", "gd-")):
            return "memory"
        if slug.endswith(("-amd", "-intel")):
            return "premium"
        return "basic"

    out = [s for s in sizes if s.get("available", True)
           and (region is None or region in s.get("regions", []))
           and (family == "all" or fam(s["slug"]) == family)]
    return sorted(out, key=lambda s: (float(s.get("price_monthly") or 0), s["slug"]))
