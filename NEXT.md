# NEXT (start here)

State: PUBLIC since 23 Nov 2026 (CI green on 3.11 to 3.13, social preview set). Not on PyPI yet. Every feature was run against a live
account (02-DECISIONS.md D7, D9, D10). Operator notes for the author's own server live outside this repo.

1. Release v0.1.0. Waiting for the owner to add the PyPI pending publisher (project `dofleet`, owner `aimanmalib`, repo `dofleet`,
   workflow `release.yml`, environment `pypi`). Then: `gh release create v0.1.0 --generate-notes` → `release.yml` builds, runs
   `twine check`, publishes to PyPI (Trusted Publishing), then publishes `server.json` to the official MCP Registry (GitHub OIDC).
   Check after: https://pypi.org/p/dofleet and `mcp-publisher` / registry search for `io.github.aimanmalib/dofleet`.
2. After PyPI is live: PR to punkpeye/awesome-mcp-servers; run the GitHub Action once for real (`uses: aimanmalib/dofleet@main`).
3. Recognition: Write for DOnations pitch (topic idea: "Never pay for a forgotten droplet again", built on `run` + budget + reaper).
4. Not yet verified: a graphical RDP session to `desktop`; GPU presets on an account with GPU access.
