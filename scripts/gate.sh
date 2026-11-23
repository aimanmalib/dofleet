#!/bin/bash
# Gate: tests + a wheel build that must carry the data files.
set -euo pipefail
cd "$(dirname "$0")/.."
uv sync -q --extra dev
uv run --extra dev pytest -q
rm -rf dist && uv build -q
# One listing, then plain greps: `unzip | grep -q` under pipefail failed at random (SIGPIPE, exit 141).
listing=$(unzip -l dist/*.whl)
for f in dofleet/locales/ms.json dofleet/data/templates/harden.sh dofleet/data/templates/_volumes.sh \
         dofleet/data/reaper_function.py; do
  grep -qF "$f" <<< "$listing" || { echo "wheel is missing $f"; exit 1; }
done
# The PyPI description must not carry links that only work on GitHub (relative paths 404 on pypi.org).
python3 scripts/check_pypi_links.py dist/*.whl
python3 -c "import ast,sys; ast.parse(open('src/dofleet/data/reaper_function.py').read())"
bash -n scripts/action.sh
for f in assets/logo.svg assets/banner-light.svg assets/banner-dark.svg assets/demo.gif assets/social.png; do [ -s "$f" ] || { echo "missing $f"; exit 1; }; done
echo "gate ok"
