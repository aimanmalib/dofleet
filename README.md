# dofleet

Disposable DigitalOcean droplets that clean up after themselves.

[Bahasa Melayu](README.ms.md)

Every droplet `dofleet` creates gets an expiry timer. When the timer runs out, `dofleet reap` (run it from cron) deletes it. You see what a batch will cost before you confirm, and what each droplet has cost so far while it runs. If the size you want is sold out in your region, `dofleet` moves to the next size or region in your preset instead of failing.

```console
$ dofleet up quick -n scrape -c 3
Preset        quick
Where         sgp1  s-4vcpu-8gb-amd  (4 vCPU / 8 GB / 160 GB)
              sgp1 s-4vcpu-8gb is out of stock, using the next choice
Names         scrape-01, scrape-02, scrape-03
Expiry timer  8h00m
Setup         harden
Cost          about $2.00 if it lives until the timer, $168.00 for a full month
Create 3 droplet(s)? [y/N]: y

Name       IP              State  Connect
scrape-01  203.0.113.10    ready  ssh ops@203.0.113.10
...
```

## Why not just doctl?

[`doctl`](https://github.com/digitalocean/doctl) is the official CLI and covers the whole API. `dofleet` does less, aimed at one job: short-lived boxes you start for a task and forget to delete.

| | doctl | dofleet |
| --- | --- | --- |
| Expiry timer + reaper for forgotten droplets | no | yes |
| Cost shown before create, spend so far in `ls` | no | yes |
| Sold-out fallback across sizes and regions | no | yes |
| Waits until SSH (or RDP) actually answers | no | yes |
| Presets and setup scripts in one TOML file | no | yes |
| Numbered menu when run without arguments | no | yes |
| English and Bahasa Melayu output | English | both |
| Everything else in the DigitalOcean API | yes | no |

If you already use doctl, `dofleet` reads its token, so there is nothing to set up.

## Install

```bash
pipx install dofleet        # or: uv tool install dofleet
```

Python 3.11 or newer. Until the first PyPI release, install from source: `pipx install git+https://github.com/aimanmalib/dofleet`.

## Token

Create a token at <https://cloud.digitalocean.com/account/api/tokens>, then either:

```bash
export DIGITALOCEAN_TOKEN=dop_v1_...
```

or let `dofleet` pick up an existing `doctl auth init` login. `dofleet whoami` shows which account and which token source it is using. For more than one account, add profiles in the config file and pass `-p <profile>`.

## Commands

| Command | What it does |
| --- | --- |
| `dofleet` | Numbered menu (in a terminal) |
| `dofleet up [preset] -n NAME -c N` | Create droplets. `--ttl 2h`, `--keep` (no timer), `-r sgp1`, `-s s-2vcpu-4gb`, `--volume 100`, `--var user=dev`, `--dry-run` |
| `dofleet ls [-m]` | Droplets with IP, age, spend so far, price per month, time left. `-m` = only ones made by dofleet |
| `dofleet extend NAME --ttl 4h` | Push the timer out. `--keep` removes it |
| `dofleet reap [--yes] [--dry-run]` | Delete dofleet droplets whose timer ran out |
| `dofleet down NAME... [--yes]` | Delete by name, id or pattern (`'web-*'`), with their dofleet volumes. A pattern only matches droplets dofleet made unless you add `--any` |
| `dofleet restart NAME... [--hard]` | Reboot, or power cycle with `--hard` |
| `dofleet ssh NAME [-- command]` | SSH in as the user the preset created, or run one command |
| `dofleet cost` | Usage this month, balance, what the running fleet costs per day and month |
| `dofleet sizes [-r REGION] [-f basic\|premium\|cpu\|memory\|gpu\|all]` | Sizes in stock, cheapest first |
| `dofleet presets` | Presets and setup templates |
| `dofleet init` | Write a starter config file |

Add `--json` before any command for machine-readable output, and `--lang ms` or `--lang en` to pick the language (default follows `LANG`).

### Run the reaper from cron

```cron
*/10 * * * * DIGITALOCEAN_TOKEN=dop_v1_... /home/you/.local/bin/dofleet reap --yes >> ~/.dofleet-reap.log 2>&1
```

`reap` also deletes dofleet volumes that have been attached to nothing for over an hour. Set `notify_cmd = ["notify-send", "dofleet"]` (any command; the message is added as the last argument) to hear about what it deleted.

`reap` only touches droplets that carry the `dofleet` tag and an expired `dofleet-exp-<unix time>` tag. Droplets you made by hand or with other tools are never deleted by it.

## Presets

Bundled presets (`dofleet presets` lists them):

| Preset | Size chain | Setup | Timer |
| --- | --- | --- | --- |
| `quick` | s-4vcpu-8gb, then the AMD and Intel twins, Singapore then Bangalore | harden | 8h |
| `tiny` | the cheapest sizes | harden | 2h |
| `docker` | s-2vcpu-4gb | docker | 1d |
| `scratch` | s-4vcpu-8gb + a 100 GB volume | harden | 6h |
| `desktop` | s-4vcpu-8gb | desktop (XFCE over RDP) | 8h |

Change them or add your own in `~/.config/dofleet/config.toml` (`dofleet init` writes a commented starter):

```toml
[defaults]
preset = "worker"
confirm_over_usd = 30      # ask twice when a batch costs more than this per month

[presets.worker]
description = "Build worker"
regions = ["sgp1", "blr1"]
sizes = ["s-2vcpu-4gb", "s-2vcpu-4gb-amd"]
image = "ubuntu-24-04-x64"
cloud_init = "docker"      # a bundled template, or a path to your own script
ttl = "12h"
tags = ["ci"]
vars = { user = "dev" }
```

A key you set overrides the bundled one; everything else stays as shipped.

## Setup templates

Templates are plain shell scripts run once by cloud-init on first boot. `#include <name>` pulls in another template, and `${user}`-style placeholders are filled from the preset's `vars`.

- `harden`: sudo user with your SSH keys, ufw firewall, fail2ban, automatic security updates, root login by key only.
- `docker`: `harden` plus Docker Engine and the compose plugin.
- `desktop`: `harden` plus an XFCE desktop over RDP. `dofleet` generates the login password and shows it once.

Your own script works the same way: `cloud_init = "~/scripts/setup.sh"`.

`dofleet up` waits until the port answers and then, over SSH, until cloud-init reports `done`, so "ready" means the setup has finished. A failed setup is shown as `setup failed`.

## Volumes

`volumes = [100, 50]` in a preset, or `--volume 100` on the command line, adds block storage to each droplet. Volumes are formatted ext4 on first boot and mounted under `/mnt/<volume name>` (DigitalOcean shows the name with underscores, e.g. `/mnt/job_01_v1`). They are tagged `dofleet` and deleted together with the droplet by `down` and `reap`; volumes you attached yourself are left alone. The cost estimate includes them.

## SSH keys

If your DigitalOcean account has no SSH key yet, `dofleet` adds your first local public key (`~/.ssh/id_ed25519.pub`, then the ecdsa and rsa keys) to the account before creating, named after the key's hash. Turn that off with `upload_local_key = "no"`. With no key anywhere, DigitalOcean emails a root password; `dofleet` then keeps root and password login on, so you are not locked out.

## Notes

- The costs shown are estimates from DigitalOcean's listed hourly and monthly prices. Backups, snapshots, volumes and bandwidth overage are not included. `dofleet cost` shows the real month-to-date figure from your account.
- A create request is never retried after a server error, because DigitalOcean may already have made the droplets. Reads and deletes are retried with backoff.
- Volume deletion finishes on DigitalOcean's side a minute or two after `down` returns.
- The create call takes at most 10 names, so bigger batches go out in groups of 10.

## Development

```bash
uv venv && uv pip install -e '.[dev]'
.venv/bin/pytest
```

The tests run against an in-memory fake of the DigitalOcean API and never touch a real account. User-facing text lives in `src/dofleet/locales/*.json`; a test fails if the English and Malay files drift apart.

## License

MIT
