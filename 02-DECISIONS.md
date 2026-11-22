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

## D8: the author's own setup stays out of this repo
The author runs `reap` from cron on a server and keeps a private preset for a disaster-recovery drill (a box with two 100 GB
volumes). Those live in a separate private config, not here, so the tool and its defaults stay generic.

## D9 (23 Nov 2026): run, budget, Functions reaper, MCP, bake, GitHub Action, GPU rule
All seven were exercised on the live account the same day:
- `run tiny --sync --pull --env`: 2.3 min end to end, output streamed, result file pulled, droplet gone. Found: a second
  run seconds after a key upload got 422 "already in use" because the key list lags; keys are now looked up by MD5
  fingerprint (`GET /account/keys/<fp>`), which matched `ssh-keygen -E md5`.
- budget: `budget_usd = 0.001` refused the create before any API write.
- Functions reaper: namespace + python:3.12 action + SCHEDULED trigger. A droplet with a 1 min timer was deleted by the
  Function at 21:15:47 while the host cron had last run at 21:10, so the Function did it. The namespace key is only
  returned on create, so install deletes and recreates the `dofleet` namespace (idempotent). The reaper code is a
  standalone stdlib file because the runtime has nothing else.
- MCP: a real `claude -p` session created `tiny`, ran a command, deleted it, and was refused `desktop` by policy.
  Hand-written JSON-RPC (no SDK dependency); the agent only sees droplets tagged `dofleet`.
- bake: snapshot of a 10 GB droplet took 34 s; `up --baked` was ready in 40 s (vs about 150 s) with the harden setup intact.
- GitHub Action: `scripts/action.sh` run locally with Actions-style env created and deleted `pr-42` and wrote ip/name outputs.
  Inputs reach the script as env vars, never pasted into shell. Not yet run on GitHub itself (repo is private).
- GPU: this account has no GPU sizes, so the error now says so (`err.size_unknown`) instead of "sold out".
Other finds: Rich swallowed `[tor1, nyc2]` in error text as markup (now escaped); DigitalOcean reuses IPs, so every
droplet gets its own known_hosts file instead of a shared one.

## D10 (23 Nov 2026): second red team (independent reviewer) and fixes
An independent review (code only, no conclusions handed over) reported 15 findings; the two high ones and one medium were
reproduced on the fake API before fixing (verify script: extend glob tagged a hand-made `web-prod`; an MCP agent deleted a
human's `db`; a missing argument crashed the MCP server). Fixed, each with a regression test:
- `extend` only acts on dofleet droplets and never adds the `dofleet` tag (a timer would hand a foreign droplet to the reaper).
- MCP agents only see droplets they created (`dofleet-mcp` tag; `scope = "all"` to widen); any exception becomes an error reply;
  extend checks the budget. Verified live: the agent could not exec on or delete `human-db`, and could on its own `agent-box`.
- Orphan volumes: age counted from a `dofleet-detached-<time>` tag set when a sweep first sees the volume detached, not from creation.
- Budget includes what running droplets will still cost (to their timer or month end) and is checked again after a dearer fallback.
- Reapers re-read each droplet just before deleting (an `extend` in between wins); the Function treats 422 as "already going".
- `install-reaper` creates the new namespace first and removes the old one only after it works. Measured: labels must be unique
  per account (422 "label already in use"), so new namespaces get `dofleet-<unix time>`; the fake API now enforces that too.
  `--every` must map to a valid cron (5m..30m, 1h..12h, 1d).
- `run`: droplets are tracked as soon as they exist (cleanup even if waiting fails); results unpacked with tarfile filter
  "data" (test with a `../../escaped.txt` member); `--env` names validated. Volume names get a random suffix.
- GitHub Action: `version` via env, `args` for run = one shell string, `down --missing-ok` instead of `|| true`, the runner key
  is always added (`DOFLEET_UPLOAD_KEY=always`), a generated password is masked and kept out of step outputs.
Not changed: the desktop password still travels in user data (readable by processes on that droplet); documented in README.

## D11: logo, banner, demo
Mark = a droplet holding a countdown ring; the amber dot marks time already gone. Colours avoid DigitalOcean's blue on purpose
(no confusion with their brand). Wordmark and tagline are outlined paths (Space Grotesk, OFL) because GitHub does not load
fonts inside SVG. `scripts/make-assets.py` rebuilds banner-{light,dark}.svg and social.png. The demo GIF is a real recording
(asciinema + agg), with spinner time compressed; nothing in it is staged.
