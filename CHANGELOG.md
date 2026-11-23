# Changelog

## Unreleased

- `notify_cmd` can carry `{message}` and `{level}` placeholders. `reap` sends `info` for droplets whose timer ran out,
  `warn` for droplets deleted because the month budget was reached, and `critical` when a delete fails (a failed delete
  used to send nothing). Messages now say why it happened and what to do. Configs without placeholders work as before.

## 0.1.0 (23 Nov 2026)

First version. Rewritten from scratch; it shares no code with the private scripts it replaces.

- `up` with presets, sold-out fallback across sizes and regions, cost shown before confirm, wait until the port answers
- Expiry timers as droplet tags, `reap` for cron, `extend`
- `ls` with spend so far and time left, `cost`, `sizes`, `down`, `restart`, `ssh`, `whoami`
- Setup templates: harden, docker, desktop (XFCE over RDP)
- English and Bahasa Melayu output, `--json` everywhere, numbered menu
- Block storage volumes (`volumes` / `--volume`): mounted on boot, deleted with the droplet, orphans reaped
- Accounts without an SSH key: local public key uploaded; with no key at all, root password login stays on
- "Ready" waits for cloud-init to finish (over SSH); setup failures are reported
- `run`: one job on a fresh droplet (copy up, run, copy back, delete), exit code passed through
- Month budget (`budget_usd`, `budget_action`): blocks creates, reaper can stop the fleet; GPU sizes need a timer
- `install-reaper`: the reaper as a scheduled DigitalOcean Function (no local cron needed)
- `mcp`: MCP server so AI agents can borrow droplets under a policy, without the token
- `bake` / `up --baked` / `snapshots`: boot from a finished setup in about 40 s
- GitHub Action (`action.yml`) for CI jobs and pull request previews
- `gpu` preset; per-droplet known_hosts (DigitalOcean reuses IPs); SSH key looked up by fingerprint
- Logo, light/dark banner, social preview, real demo GIF in the README; security model section
- Second red team: extend/MCP scoping, detached-volume clock, committed spend in the budget, reaper re-check before delete,
  new-before-old reaper install, safe tar extraction, Action input hardening (02-DECISIONS.md D10)
- Safety: glob patterns in `down` skip droplets dofleet did not make (`--any` to include); create is never retried after 5xx;
  `reap` keeps going when one delete fails and treats 404 as done; `notify_cmd` hook
