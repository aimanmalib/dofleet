#!/bin/bash
# Body of the GitHub Action (action.yml). Inputs arrive as env vars so nothing user-supplied is pasted into shell code.
set -euo pipefail
if [ -n "${DOFLEET_CONFIG_TEXT:-}" ]; then
  export DOFLEET_CONFIG="$RUNNER_TEMP/dofleet-config.toml"
  printf '%s\n' "$DOFLEET_CONFIG_TEXT" > "$DOFLEET_CONFIG"
fi
mkdir -p ~/.ssh && [ -f ~/.ssh/id_ed25519 ] || ssh-keygen -q -t ed25519 -N "" -f ~/.ssh/id_ed25519
read -r -a extra <<< "${DOFLEET_ARGS:-}"
out="$RUNNER_TEMP/dofleet.json"
case "$DOFLEET_CMD" in
  up)   dofleet --json up "$DOFLEET_PRESET" -n "$DOFLEET_NAME" --ttl "$DOFLEET_TTL" --yes "${extra[@]}" > "$out" ;;
  down) dofleet --json down "$DOFLEET_NAME" --yes "${extra[@]}" > "$out" || true ;;
  run)  echo '{}' > "$out"; dofleet run "$DOFLEET_PRESET" -n "$DOFLEET_NAME" --ttl "$DOFLEET_TTL" --yes -- "${extra[@]}" ;;
  reap) dofleet --json reap --yes > "$out" ;;
  *)    echo "unknown command: $DOFLEET_CMD" >&2; exit 2 ;;
esac
python3 - "$out" >> "$GITHUB_OUTPUT" <<'PY'
import json, sys
text = open(sys.argv[1]).read()
start = text.find("{")
data = json.loads(text[start:]) if start >= 0 else {}
first = (data.get("droplets") or [{}])[0] if isinstance(data, dict) else {}
first = first if isinstance(first, dict) else {"name": first}
print(f"ip={first.get('ip') or ''}")
print(f"name={first.get('name') or ''}")
print("json=" + json.dumps(data))
PY
