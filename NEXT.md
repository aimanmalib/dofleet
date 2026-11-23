# NEXT (start here)

State: public since 23 Nov 2026 (CI green on 3.11 to 3.13, social preview set). 0.1.0 on PyPI + MCP Registry; `main` carries
0.1.1 (not released yet). Every feature was run against a live account (02-DECISIONS.md D7, D9, D10, D15, D16). Operator notes
for the author's own server live outside this repo.

1. Release 0.1.1 (waiting for the owner's go): `gh release create v0.1.1` → release.yml does PyPI + registry. Afterwards check
   `https://pypi.org/pypi/dofleet/json` (version, links), the registry (`/v0/servers?search=dofleet`), and run
   `dofleet install-reaper --every 10m --yes` on accounts with the Function reaper so it gets the tag sweep.
   Version lives in pyproject.toml, server.json (twice) and `src/dofleet/__init__.py`; `tests/test_release.py` fails if they differ.
2. GitHub Action: run for real on GitHub 23 Nov (workflow `action self-test`, manual). To run it again: set the repository secret
   `DIGITALOCEAN_TOKEN` (a test account token), `gh workflow run action-selftest.yml`, check that no droplet or `dofleet-*` SSH key
   is left on the account, then delete the secret.
3. Listings: official MCP Registry done. Glama (needs the owner's GitHub login) → then the punkpeye/awesome-mcp-servers PR
   (Cloud Platforms; needs the Glama score badge). mcp.so, mcpservers.org, MCP Market, DigitalOcean Community Tools: forms.
   PulseMCP picks up the registry by itself when submissions reopen. Write for DOnations is paused (checked 23 Nov 2026).
4. Not yet verified: a graphical RDP session to `desktop`; GPU presets on an account with GPU access.
