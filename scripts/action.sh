#!/bin/bash
# Body of the GitHub Action (action.yml). Inputs arrive as env vars so nothing user-supplied is pasted into shell code.
set -euo pipefail
if [ -n "${DOFLEET_CONFIG_TEXT:-}" ]; then
  export DOFLEET_CONFIG="$RUNNER_TEMP/dofleet-config.toml"
  printf '%s\n' "$DOFLEET_CONFIG_TEXT" > "$DOFLEET_CONFIG"
fi
mkdir -p ~/.ssh && [ -f ~/.ssh/id_ed25519 ] || ssh-keygen -q -t ed25519 -N "" -f ~/.ssh/id_ed25519
export DOFLEET_UPLOAD_KEY=always   # the runner's fresh key must reach the droplet even when the account has keys
# ...and comes off the account again when this step ends: the droplet already has it, and otherwise every CI run would
# leave one more SSH key on the account (measured: 2 per self-test run). A key that was there before the step stays.
key_py="$DOFLEET_ACTION_PATH/scripts/action_key.py"
key_before=$(python3 "$key_py" find ~/.ssh/id_ed25519.pub || echo "?")
trap 'python3 "$key_py" forget ~/.ssh/id_ed25519.pub "$key_before" || true' EXIT
extra=()
[ "$DOFLEET_CMD" = run ] || read -r -a extra <<< "${DOFLEET_ARGS:-}"
out="$RUNNER_TEMP/dofleet.json"
case "$DOFLEET_CMD" in
  up)   dofleet --json up "$DOFLEET_PRESET" -n "$DOFLEET_NAME" --ttl "$DOFLEET_TTL" --yes "${extra[@]}" > "$out" ;;
  down) dofleet --json down "$DOFLEET_NAME" --yes --missing-ok "${extra[@]}" > "$out" ;;
  run)  echo '{}' > "$out"; dofleet run "$DOFLEET_PRESET" -n "$DOFLEET_NAME" --ttl "$DOFLEET_TTL" --yes -- bash -lc "$DOFLEET_ARGS" ;;
  reap) dofleet --json reap --yes > "$out" ;;
  *)    echo "unknown command: $DOFLEET_CMD" >&2; exit 2 ;;
esac
# fd 3 = the step's real stdout (workflow commands such as ::add-mask:: are read there); stdout goes to the outputs file
python3 - "$out" 3>&1 >> "$GITHUB_OUTPUT" <<'PY'
import json, os, sys
text = open(sys.argv[1]).read()
start = text.find("{")
data = json.loads(text[start:]) if start >= 0 else {}
password = (data.pop("generated", None) or {}).get("password") if isinstance(data, dict) else None
if password:  # hide it from the log, and keep it out of the step outputs
    os.write(3, f"::add-mask::{password}\n".encode())
first = (data.get("droplets") or [{}])[0] if isinstance(data, dict) else {}
first = first if isinstance(first, dict) else {"name": first}
print(f"ip={first.get('ip') or ''}")
print(f"name={first.get('name') or ''}")
print("json=" + json.dumps(data))
PY
