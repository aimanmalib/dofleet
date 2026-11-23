"""The Action removes the runner key it added to the account, and only that key (scripts/action_key.py)."""

import importlib.util
import pathlib
import subprocess

import httpx

from fake_do import FakeDO

ROOT = pathlib.Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("action_key", ROOT / "scripts" / "action_key.py")
action_key = importlib.util.module_from_spec(spec)
spec.loader.exec_module(action_key)


def _setup(tmp_path):
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(tmp_path / "k")], check=True)
    pub = (tmp_path / "k.pub").read_text()
    fd = FakeDO()
    http = httpx.Client(transport=fd.transport(), base_url="https://api.digitalocean.com/v2")

    def call(method, path):
        r = http.request(method, path)
        return r.status_code, (r.json() if r.content else {})

    def upload(name):
        http.post("/account/keys", json={"name": name, "public_key": pub})
    return fd, call, pub, upload


def test_key_added_by_the_step_is_removed(tmp_path):
    fd, call, pub, upload = _setup(tmp_path)
    before = action_key.find(call, pub)
    assert before == ""
    upload("dofleet-0123456789")  # what `dofleet up` does with DOFLEET_UPLOAD_KEY=always
    assert action_key.forget(call, pub, before) == "dofleet-0123456789"
    assert [k["name"] for k in fd.keys] == ["laptop"]


def test_key_that_was_already_there_stays(tmp_path):
    fd, call, pub, upload = _setup(tmp_path)
    upload("dofleet-0123456789")  # a self-hosted runner whose key an earlier run (or the owner) left on the account
    before = action_key.find(call, pub)
    assert before not in ("", "?")
    assert action_key.forget(call, pub, before) is None
    assert "dofleet-0123456789" in [k["name"] for k in fd.keys]


def test_unknown_state_or_foreign_name_is_left_alone(tmp_path):
    fd, call, pub, upload = _setup(tmp_path)
    upload("my-laptop")  # not named by dofleet
    assert action_key.forget(call, pub, "") is None and "my-laptop" in [k["name"] for k in fd.keys]
    assert action_key.forget(call, pub, "?") is None  # find could not tell: never delete


def test_action_script_wires_it_up():
    text = (ROOT / "scripts" / "action.sh").read_text()
    assert 'scripts/action_key.py"' in text and '"$key_py" find' in text
    assert "trap 'python3 \"$key_py\" forget" in text
