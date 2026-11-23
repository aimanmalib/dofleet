import pytest

from dofleet import cli, ready
from dofleet.api import DOClient
from fake_do import FakeDO


@pytest.fixture
def fake(monkeypatch, tmp_path):
    """Fake DigitalOcean API wired into the CLI; ``fake.cfg`` is the config file the CLI reads."""
    fd = FakeDO()
    cfg = tmp_path / "config.toml"
    monkeypatch.setenv("DOFLEET_CONFIG", str(cfg))
    monkeypatch.setenv("DOFLEET_LANG", "en")
    monkeypatch.setenv("DIGITALOCEAN_TOKEN", "t")
    monkeypatch.setenv("HOME", str(tmp_path))  # no real ~/.ssh keys leak into tests
    cli.S._client = DOClient("t", transport=fd.transport(), sleep=lambda s: None)
    monkeypatch.setattr(ready, "port_open", lambda ip, port, timeout=5.0: True)
    monkeypatch.setattr(ready, "cloud_init_state", lambda ip, identity=None, droplet_id=None: "done")
    monkeypatch.setattr(ready.time, "sleep", lambda s: None)
    fd.cfg = cfg
    yield fd
    cli.S._client = None
