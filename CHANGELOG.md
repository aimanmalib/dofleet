# Changelog

## 0.1.0 (unreleased)

First version. Rewritten from scratch; it shares no code with the private scripts it replaces.

- `up` with presets, sold-out fallback across sizes and regions, cost shown before confirm, wait until the port answers
- Expiry timers as droplet tags, `reap` for cron, `extend`
- `ls` with spend so far and time left, `cost`, `sizes`, `down`, `restart`, `ssh`, `whoami`
- Setup templates: harden, docker, desktop (XFCE over RDP)
- English and Bahasa Melayu output, `--json` everywhere, numbered menu
- Block storage volumes (`volumes` / `--volume`): mounted on boot, deleted with the droplet, orphans reaped
- Accounts without an SSH key: local public key uploaded; with no key at all, root password login stays on
- "Ready" waits for cloud-init to finish (over SSH); setup failures are reported
- Safety: glob patterns in `down` skip droplets dofleet did not make (`--any` to include); create is never retried after 5xx;
  `reap` keeps going when one delete fails and treats 404 as done; `notify_cmd` hook
