# Decisions

## D1 (23 Nov 2026): rewrite, not a cleanup of do-manager
The old private `aimanmalib/do-manager` was a menu around the same calls `doctl` already makes, plus a Windows RDP
script and unrelated files (a TikTok view bot, a baked-in password, PyInstaller .exe files). Cleaning it up would still
leave a weaker doctl. Owner asked for a new repo with new behaviour. The new tool targets one job doctl does not do:
short-lived droplets that get deleted on time. No code or history is carried over; the old repo stays private.

## D2: expiry lives in DigitalOcean tags, not a local database
`dofleet` + `dofleet-exp-<unix time>`. Any machine with the token can reap; nothing to lose if the laptop dies.
`reap` refuses droplets without the `dofleet` marker tag, so a stray `dofleet-exp-*` tag on a hand-made droplet is ignored.
Undo: `dofleet extend NAME --keep` removes the timer.

## D3: httpx directly instead of pydo (the official Python client)
dofleet uses about 15 endpoints. A thin client keeps the install small and lets the tests run against an
`httpx.MockTransport` fake with no network. Revisit if the endpoint list grows past what one file can hold.

## D4: setup templates are shell scripts, not cloud-config YAML
Composable with `#include`, readable by anyone, no YAML dependency. cloud-init runs a `#!/bin/bash` user_data as-is.
Placeholder values are limited to a safe character set because they are pasted into shell.

## D5: owner's fixed values
1. Bilingual: every user-facing string in `locales/en.json` + `locales/ms.json`; a test fails when keys or placeholders differ.
2. Product-grade UX: menu for non-CLI users, plan + cost shown before anything is created, typed confirmation above a cost limit.
3. Change without code: presets, fallback chains, timers, limits and language live in `data/presets.toml`,
   overridden by the user's `config.toml`; setup scripts are files.
4. Small modules (each under 400 lines), decisions here, undo noted per decision.

## D6: region order beats size order in fallback
A user who asks for Singapore would rather get the AMD twin in Singapore than the basic size in Bangalore.

## D7 (23 Nov 2026): red team against a real account, and what changed
Measured on a real DigitalOcean account (sgp1, 3 droplets created and deleted, total cost under $0.10):
- **Lockout:** account with no SSH key + `harden` (PermitRootLogin prohibit-password, password auth off) = the emailed root
  password is useless and the box is unreachable. Fix: upload the local public key when the account has none; with no key
  anywhere keep root + password login on (`root_login`, `password_auth` template vars). Test: `test_up_without_any_key_*`.
- **"Ready" too early:** port 22 opened about a minute before cloud-init finished (ops user missing). Fix: poll
  `cloud-init status` over SSH; `unknown` (no working key) falls back to the port check.
- **Duplicate droplets:** POST /droplets was retried on 5xx. A 5xx on create can still create droplets. Fix: POST retries on 429 only.
- **`down '*'`** would delete droplets made by hand. Fix: patterns skip unmanaged droplets unless `--any`; exact names/ids always work.
- **Volumes:** attaching at create did not mount anything (filesystem stayed empty, nothing in `df`). Fix: our own mount step
  (`_volumes.sh`), run before the template. Selective destroy works but is asynchronous (volume gone 30 to 90 s later).
- **Key name leaked the host name** (`dofleet-ip-<host ip>`). Fix: name = hash of the key.
Verified on the droplet: cloud-init `done`, sudo without password, ufw active, fail2ban active, `passwordauthentication no`,
password login refused, root by key works; desktop: xrdp active, 3389 reachable, generated password matches /etc/shadow and is
not in cloud-init-output.log; volume mounted at `/mnt/<name>`. Not verified: a full graphical RDP session.

## D8: host integration
`~/ops/dofleet` runs `reap` every 10 minutes on the host and holds the `gerudi` preset for the disaster-recovery drill
(`~/ops/jaring/PULIH-BENCANA.md`). That lives outside this repo on purpose: the tool stays generic.
