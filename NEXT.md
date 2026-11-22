# NEXT (start here)

State: 0.1.0 code complete. Tests pass against the fake API, and the full cycle was run on a real account on 23 Nov 2026
(D7 in 02-DECISIONS.md). Private repo, not on PyPI. Host runs `reap` from cron (`~/ops/dofleet/README.md`).

1. Owner decision: make the repo public (aimanmalib or sasateguh org), then `gilap topik` for topics + tag `digitalocean-community-tools`.
2. Publish 0.1.0 to PyPI (name `dofleet` was free on 23 Nov 2026).
3. Owner: replace the host token (drill token from 20 Nov) with a scoped one: droplet, volume, ssh_key, tag, account:read.
4. Recognition: pitch a Write for DOnations tutorial built around dofleet.
5. Not yet verified: a full graphical RDP session to the `desktop` preset.
