# NEXT (start here)

State: feature complete for a first release. Every feature was run against a live account on 23 Nov 2026 (02-DECISIONS.md D7, D9, D10).
Not on PyPI yet. Operator notes for the author's own server (token, cron, drill preset) live outside this repo.

1. Publish: make the repo public, tag `v0.1.0`, release to PyPI with Trusted Publishing (name `dofleet` was free on 23 Nov 2026).
   README images are relative; the build rewrites them to absolute URLs for PyPI, so they work there once the repo is public.
2. After going public: Social preview = `assets/social.png` (GitHub shows that setting for public repos only); add a CI badge
   for `.github/workflows/ci.yml`; run the GitHub Action once for real (`uses: <owner>/dofleet@main`).
3. Recognition: tag `digitalocean-community-tools` (done), pitch a Write for DOnations tutorial built on `run` + budget + reaper.
4. Not yet verified: a graphical RDP session to `desktop`; GPU presets on an account with GPU access.
