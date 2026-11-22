# NEXT (start here)

State: PUBLIC since 23 Nov 2026 (CI green on 3.11 to 3.13, social preview set). Released 0.1.0 on PyPI + MCP Registry. Every feature was run against a live
account (02-DECISIONS.md D7, D9, D10). Operator notes for the author's own server live outside this repo.

1. DONE 23 Nov 2026: v0.1.0 on PyPI (https://pypi.org/project/dofleet/, Trusted Publishing) and on the official MCP Registry
   (`io.github.aimanmalib/dofleet`, active). Next release: bump version in pyproject.toml AND server.json (both places), then
   `gh release create vX.Y.Z` → release.yml does PyPI + registry.
2. After PyPI is live: PR to punkpeye/awesome-mcp-servers; run the GitHub Action once for real (`uses: aimanmalib/dofleet@main`).
3. Launch video (sources private, ~/dofleet-media/brag: brag-plan.md, garis.json, kongsi.txt captions): rendered 23 Nov;
   owner picks the 'dofleet' pronunciation (FILE DROP samples A/B/C), then regenerate lines reveal + tutup and re-render.
4. Recognition: Write for DOnations pitch (topic idea: "Never pay for a forgotten droplet again", built on `run` + budget + reaper).
5. Not yet verified: a graphical RDP session to `desktop`; GPU presets on an account with GPU access.
