#!/bin/bash
# Gate: tests + a wheel build that must carry the data files.
set -euo pipefail
cd "$(dirname "$0")/.."
uv sync -q --extra dev
uv run --extra dev pytest -q
rm -rf dist && uv build -q
unzip -l dist/*.whl | grep -q "dofleet/locales/ms.json"
unzip -l dist/*.whl | grep -q "dofleet/data/templates/harden.sh"
unzip -l dist/*.whl | grep -q "dofleet/data/templates/_volumes.sh"
unzip -l dist/*.whl | grep -q "dofleet/data/reaper_function.py"
python3 -c "import ast,sys; ast.parse(open('src/dofleet/data/reaper_function.py').read())"
bash -n scripts/action.sh
for f in assets/logo.svg assets/banner-light.svg assets/banner-dark.svg assets/demo.gif assets/social.png; do [ -s "$f" ] || { echo "missing $f"; exit 1; }; done
echo "gate ok"
