# NEXT (start here)

State: feature complete for a first release (D7 + D9 in 02-DECISIONS.md, every feature run on a live account 23 Nov 2026).
Private repo, not on PyPI. The host runs `reap` from cron and the account also has the Functions reaper (`dofleet` namespace, sgp1, every 10 min).

1. Owner decision: make the repo public (aimanmalib or sasateguh), then `gilap topik` + tag `digitalocean-community-tools`.
   The GitHub Action (`uses: aimanmalib/dofleet@main`) only works once the repo is public; test it there first.
2. Publish to PyPI (name `dofleet` was free on 23 Nov 2026). README images are relative; the build rewrites them to absolute
   URLs for PyPI (hatch-fancy-pypi-readme), so they only work on PyPI once the repo is public.
   Right after going public (a session, not the owner): upload `assets/social.png` as Social preview through `pandu`
   (Settings -> Social preview; the section does not exist while the repo is private, measured 23 Nov).
3. Owner: replace the host token (drill token from 20 Nov) with a scoped one, then `dofleet install-reaper --every 10m`
   again so the Function gets the new token.
4. Recognition: Write for DOnations pitch, e.g. "Never pay for a forgotten droplet again" built on `run` + budget + reaper.
5. Not yet verified: a graphical RDP session to `desktop`; GPU presets on an account with GPU access.
