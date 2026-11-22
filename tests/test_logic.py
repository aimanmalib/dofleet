import json
from importlib import resources

import pytest

from dofleet import cloudinit, config, fleet, i18n, placement
from fake_do import REGIONS, SIZES


def test_durations():
    assert fleet.parse_duration("30m") == 1800
    assert fleet.parse_duration(" 2H ") == 7200
    assert fleet.parse_duration("1w") == 604800
    for bad in ("", "0h", "2", "h", "1.5h", "-1h", "2y"):
        with pytest.raises(fleet.DurationError):
            fleet.parse_duration(bad)
    assert fleet.format_duration(3 * 86400 + 4 * 3600) == "3d4h"
    assert fleet.format_duration(-90) == "-1m"


def test_names():
    assert fleet.sanitize_name("My Box_1!!") == "My-Box-1"
    assert fleet.sanitize_name("***") == "droplet"
    assert fleet.numbered_names("web", 1, set()) == ["web"]
    assert fleet.numbered_names("web", 3, {"web-02"}) == ["web-01", "web-03", "web-04"]


def test_expiry_and_cost():
    d = {"tags": ["dofleet", "dofleet-exp-500", "dofleet-exp-300", "dofleet-exp-x"],
         "created_at": "2026-01-01T00:00:00Z", "size": {"price_hourly": 0.1, "price_monthly": 50}}
    assert fleet.expires_at(d) == 300
    assert fleet.expired([d], 299) == [] and fleet.expired([d], 300) == [d]
    start = fleet.created_ts(d)
    assert fleet.accrued(d, start + 10 * 3600) == pytest.approx(1.0)
    assert fleet.accrued(d, start + 10_000 * 3600) == 50  # capped at monthly price
    assert fleet.batch_cost(0.1, 50, 3, 7200) == (pytest.approx(0.6), 150)
    assert fleet.batch_cost(0.1, 50, 2, None) == (100, 100)


def test_match():
    ds = [{"id": 1, "name": "web-01"}, {"id": 2, "name": "web-02"}, {"id": 3, "name": "db"}]
    assert [d["id"] for d in fleet.match(ds, ["web-*"])] == [1, 2]
    assert [d["id"] for d in fleet.match(ds, ["3", "db"])] == [3]
    assert fleet.match(ds, ["nope"]) == []


def test_placement_prefers_region_then_falls_back():
    c = placement.choose(["sgp1", "blr1"], ["s-4vcpu-8gb", "s-4vcpu-8gb-amd"], SIZES, REGIONS)
    assert (c.region, c.size["slug"], c.fell_back) == ("sgp1", "s-4vcpu-8gb-amd", True)
    c = placement.choose(["blr1"], ["s-4vcpu-8gb"], SIZES, REGIONS)
    assert (c.region, c.fell_back) == ("blr1", False)
    c = placement.choose(["sgp1"], ["s-4vcpu-8gb-amd"], SIZES, REGIONS, skip={("sgp1", "s-4vcpu-8gb-amd")})
    assert c is None
    assert placement.choose(["nyc1"], ["s-1vcpu-1gb"], SIZES, REGIONS) is None


def test_filter_sizes_sorted_and_family():
    out = placement.filter_sizes(SIZES, "sgp1", "all")
    assert [s["slug"] for s in out] == ["s-1vcpu-1gb", "s-4vcpu-8gb-amd"]
    assert [s["slug"] for s in placement.filter_sizes(SIZES, None, "premium")] == ["s-4vcpu-8gb-amd"]


def test_templates_render_and_include():
    text, gen = cloudinit.render("docker", {"user": "dev"})
    assert text.startswith("#!/bin/bash")
    assert text.count("#!/bin/bash") == 1  # include strips the second shebang
    assert "adduser --disabled-password --gecos \"\" dev" in text and "docker.io" in text
    assert gen == {}
    text, gen = cloudinit.render("desktop", {})
    assert len(gen["password"]) == 20 and gen["password"] in text
    assert "port=3389" in text
    assert cloudinit.render(None) == (None, {})
    with pytest.raises(cloudinit.TemplateError):
        cloudinit.render("harden", {"user": "x; rm -rf /"})
    with pytest.raises(cloudinit.TemplateError):
        cloudinit.render("no-such-template")


def test_own_template_file(tmp_path):
    f = tmp_path / "mine.sh"
    f.write_text("#!/bin/bash\n#include harden\necho hi ${user} $HOME\n")
    text, _ = cloudinit.render(str(f), {"user": "z"})
    assert "ufw" in text and "echo hi z $HOME" in text


def test_bundled_presets_are_valid():
    s = config.load(config.Path("/nonexistent/config.toml"))
    for name in s.presets:
        p = s.preset(name)
        if p.get("cloud_init"):
            cloudinit.render(p["cloud_init"], p.get("vars"))
        if p.get("ttl"):
            fleet.parse_duration(p["ttl"])


def test_user_config_merges(tmp_path, monkeypatch):
    f = tmp_path / "c.toml"
    f.write_text('[defaults]\nlang = "ms"\n[presets.quick]\nregions = ["fra1"]\n[presets.mine]\nregions="sgp1"\nsizes=["s-1vcpu-1gb"]\n')
    s = config.load(f)
    assert s.defaults["lang"] == "ms" and s.defaults["preset"] == "quick"
    assert s.preset("quick")["regions"] == ["fra1"] and s.preset("quick")["ttl"] == "8h"
    assert s.preset("mine")["regions"] == ["sgp1"]
    with pytest.raises(config.ConfigError):
        s.preset("nope")


def test_token_order(tmp_path, monkeypatch):
    for e in config.LEGACY_TOKEN_ENVS:
        monkeypatch.delenv(e, raising=False)
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    s = config.load(tmp_path / "none.toml")
    with pytest.raises(config.ConfigError):
        s.token()
    (tmp_path / "doctl").mkdir()
    (tmp_path / "doctl" / "config.yaml").write_text("access-token: dop_v1_fromdoctl\ncontext: default\n")
    assert s.token() == ("dop_v1_fromdoctl", "doctl config")
    monkeypatch.setenv("DIGOCEAN_TOKEN", "legacy")
    assert s.token()[0] == "legacy"
    monkeypatch.setenv("DIGITALOCEAN_TOKEN", "main")
    assert s.token() == ("main", "$DIGITALOCEAN_TOKEN")


def test_locales_complete_and_formatting():
    folder = resources.files("dofleet").joinpath("locales")
    en = json.loads(folder.joinpath("en.json").read_text())
    ms = json.loads(folder.joinpath("ms.json").read_text())
    assert set(en) == set(ms)
    import re
    for k in en:
        assert set(re.findall(r"{(\w+)}", en[k])) == set(re.findall(r"{(\w+)}", ms[k])), k


def test_lang_resolve(monkeypatch):
    for e in ("DOFLEET_LANG", "LC_ALL", "LC_MESSAGES"):
        monkeypatch.delenv(e, raising=False)
    monkeypatch.setenv("LANG", "ms_MY.UTF-8")
    assert i18n.resolve() == "ms"
    monkeypatch.setenv("LC_ALL", "C.UTF-8")  # C locale says nothing about language, LANG still counts
    assert i18n.resolve() == "ms"
    monkeypatch.setenv("LC_ALL", "en_US.UTF-8")
    assert i18n.resolve() == "en"
    assert i18n.resolve("en") == "en"
    assert i18n.resolve(None, "fr") == "en"
