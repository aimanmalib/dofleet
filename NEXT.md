# NEXT (start here)

State: public since 23 Nov 2026 (CI green on 3.11 to 3.13, social preview set). 0.1.1 released 23 Nov 2026 on PyPI + MCP Registry
(isLatest). Features were run against a live account (02-DECISIONS.md D7, D9, D10, D15, D16), except item 4. Operator notes for the
author's own server live outside this repo.

1. DONE 23 Nov 2026: v0.1.1 (release.yml: build, PyPI, registry all green; `uvx --from dofleet==0.1.1 dofleet --version` checked).
   Next release: bump the version in pyproject.toml, server.json (twice) and `src/dofleet/__init__.py` (`tests/test_release.py`
   fails if they differ), then `gh release create vX.Y.Z`. Accounts with the Function reaper: `dofleet install-reaper` again.
2. GitHub Action: run for real on GitHub 23 Nov (workflow `action self-test`, manual). To run it again: set the repository secret
   `DIGITALOCEAN_TOKEN` (a test account token), `gh workflow run action-selftest.yml`, check that no droplet or `dofleet-*` SSH key
   is left on the account, then delete the secret.
3. Listings (23 Nov 2026): official MCP Registry; Glama approved, rated B (badge in README); punkpeye/awesome-mcp-servers
   PR #20474 (Cloud Platforms, after `agentmetal/mcp`; merges come in batches, median about 9 days); mcpservers.org submitted
   (free review, up to 2 weeks); DigitalOcean Community Tools form submitted, not public yet (check
   https://www.digitalocean.com/rss/community/tools.atom). MCP Market and mcp.so only offered paid listings (skipped). PulseMCP
   picks up the registry by itself when submissions reopen. Write for DOnations is paused.
4. Not yet verified: a graphical RDP session to `desktop`; GPU presets on an account with GPU access.
