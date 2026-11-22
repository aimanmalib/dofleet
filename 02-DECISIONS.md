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
