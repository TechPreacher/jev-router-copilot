#!/usr/bin/env bash
# Install the Model router for GitHub Copilot. Copilot CLI and the VS Code Copilot harness both read ~/.copilot.
#   ./install.sh                          installs into ~/.copilot
#   COPILOT_HOME=/some/dir ./install.sh   installs into /some/dir instead
#   ./install.sh --tier2                  also installs the Tier 2 fallback (router_mcp.py + sessionStart hook)
# Safe to re-run: files are updated in place, a changed file is first kept as <name>.bak-<timestamp>, and the
# hook file is rewritten from the template. A fresh install leaves the router OFF. An existing on/off switch and
# its stats are kept. Nothing is sent to TypeSafe during install. The installer never writes settings.json,
# mcp-config.json or your shell rc files: it prints the snippets and the PATH line for you to add.
set -euo pipefail

TIER2=0
for arg in "$@"; do
  case "$arg" in
    --tier2) TIER2=1 ;;
    -h|--help) sed -n '2,8p' "$0"; exit 0 ;;
    *) echo "error: unknown option $arg (try --help)"; exit 2 ;;
  esac
done

HERE="$(cd "$(dirname "$0")" && pwd)"
SRC="$HERE/files"
CP="${COPILOT_HOME:-$HOME/.copilot}"
JR="$CP/model-router"
STAMP="$(date +%Y%m%d-%H%M%S)"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

command -v python3 >/dev/null || { echo "error: python3 not found. Install it first (macOS: xcode-select --install)."; exit 1; }
[ -f "$SRC/router.py" ] || { echo "error: $SRC/router.py not found. Run install.sh from the project checkout."; exit 1; }

# install_file SRC DST: copy unless identical; a changed DST is kept as DST.bak-<timestamp> first.
install_file() {
  local src="$1" dst="$2"
  if [ -f "$dst" ] && cmp -s "$src" "$dst"; then
    return 0
  fi
  if [ -f "$dst" ]; then
    cp "$dst" "$dst.bak-$STAMP"
    echo "  kept previous $(basename "$dst") as $(basename "$dst").bak-$STAMP"
  fi
  cp "$src" "$dst"
}

# render TEMPLATE OUT: replaces @JR@ with the install dir (escaped for JSON) and @PY@ with the interpreter
# command (a bare python3 here; install.ps1 puts an absolute path there). A .json output is validated.
render() {
  python3 -I - "$1" "$2" "$JR" <<'PY'
import json, sys
src, dst, jr = sys.argv[1:4]
with open(src, encoding="utf-8") as f:
    text = f.read().replace("@JR@", json.dumps(jr, ensure_ascii=False)[1:-1]).replace("@PY@", "python3")
if dst.endswith(".json"):
    text = json.dumps(json.loads(text), indent=2) + "\n"
with open(dst, "w", encoding="utf-8") as f:
    f.write(text)
PY
}

echo "Installing Model router into $CP"
# An install made under the old name (jev-router) moves over: models.json, state and stats are kept, the old hook,
# agents, skill and scripts are removed. settings.json and mcp-config.json are never touched, so an old statusLine
# or mcpServers entry pointing at jev-router/ must be updated by hand; a note is printed below.
OLD_JR="$CP/jev-router"
MIGRATED=0
if [ -d "$OLD_JR" ] && [ ! -d "$JR" ]; then
  mv "$OLD_JR" "$JR"
  rm -f "$JR"/jev_*.py "$JR/bin/jevcp" "$JR/bin/jevcp.ps1" "$JR"/agents/jev-*.agent.md.tmpl
  rm -f "$CP/hooks/jev-router.json" "$CP/hooks/jev-router-session.json"
  for size in tiny everyday large hardest; do rm -f "$CP/agents/jev-$size.agent.md"; done
  rm -rf "$CP/skills/jev-router"
  MIGRATED=1
  echo "  migrated the jev-router install to $JR (models.json, state and stats kept; old hook, agents, skill and scripts removed)"
fi
mkdir -p "$JR/bin" "$CP/agents" "$CP/hooks" "$CP/skills/model-router"

install_file "$SRC/router.py" "$JR/router.py"
install_file "$SRC/router_copilot.py" "$JR/router_copilot.py"
install_file "$SRC/router_compat.py" "$JR/router_compat.py"
install_file "$SRC/router_statusline.py" "$JR/router_statusline.py"
install_file "$SRC/bin/routercp" "$JR/bin/routercp"
install_file "$SRC/bin/routercp.ps1" "$JR/bin/routercp.ps1"
chmod 755 "$JR/bin/routercp" "$JR/router_statusline.py"
# Agent files are rendered from templates and models.json (per-size model, effort, policy, label).
# The templates are installed too, so `router_copilot.py model ...` can re-render an agent file later without this script.
# An existing models.json is never overwritten: a re-install keeps the user's model choices.
mkdir -p "$JR/agents" "$STAGE/agents"
for f in "$SRC"/agents/router-*.agent.md.tmpl; do
  install_file "$f" "$JR/agents/$(basename "$f")"
done
COPILOT_HOME="$CP" python3 -I "$JR/router_copilot.py" render-agents "$STAGE/agents" >/dev/null
for f in "$STAGE"/agents/router-*.agent.md; do
  install_file "$f" "$CP/agents/$(basename "$f")"
done

render "$SRC/hooks/model-router.json.tmpl" "$STAGE/model-router.json"
install_file "$STAGE/model-router.json" "$CP/hooks/model-router.json"
render "$SRC/skills/model-router/SKILL.md" "$STAGE/SKILL.md"
install_file "$STAGE/SKILL.md" "$CP/skills/model-router/SKILL.md"

if [ "$TIER2" = 1 ]; then
  install_file "$SRC/router_mcp.py" "$JR/router_mcp.py"
  chmod 755 "$JR/router_mcp.py"
  render "$SRC/hooks/model-router-session.json.tmpl" "$STAGE/model-router-session.json"
  install_file "$STAGE/model-router-session.json" "$CP/hooks/model-router-session.json"
  echo "  Tier 2 installed (session hook + router_mcp.py). It is NOT registered yet; see the snippet below."
fi

# Fresh install: OFF. A re-install keeps whatever on/off state and stats the user already has.
if [ ! -f "$JR/state.json" ]; then
  python3 -I "$JR/router_copilot.py" off >/dev/null
fi

# Self-test in a scratch state dir, which is OFF by default, so nothing is sent anywhere.
# The hook must print nothing and exit 0. The status line must print "Router OFF".
mkdir -p "$STAGE/selftest"
PAYLOAD='{"sessionId":"install-selftest","prompt":"install self-test","transformedPrompt":"install self-test"}'
set +e
OUT="$(printf '%s' "$PAYLOAD" | MODEL_ROUTER_HOME="$STAGE/selftest" python3 -I "$JR/router_copilot.py" transform)"
RC=$?
LINE="$(MODEL_ROUTER_HOME="$STAGE/selftest" python3 -I "$JR/router_statusline.py" </dev/null)"
set -e
if [ "$RC" != 0 ] || [ -n "$OUT" ]; then
  echo "error: self-test failed (exit $RC, output: $OUT). Files are installed; fix this before using the router."
  exit 1
fi
if [ "$LINE" != "Router OFF" ]; then
  echo "error: status line self-test printed '$LINE' instead of 'Router OFF'. Files are installed; check router_statusline.py."
  exit 1
fi

python3 -I "$JR/router_copilot.py" status > "$STAGE/status.txt"
echo
echo "Self-test passed (hook is silent while OFF, exit 0; status line prints 'Router OFF')."
echo "Done. $(head -1 "$STAGE/status.txt")"
if [ "$MIGRATED" = 1 ]; then
  for f in "$CP/settings.json" "$CP/mcp-config.json"; do
    if [ -f "$f" ] && grep -q "jev-router/" "$f"; then
      echo "NOTE: $f still points at jev-router/; change that path to model-router/ (and jev_statusline.py to router_statusline.py, jev_mcp.py to router_mcp.py) yourself."
    fi
  done
fi

if ! python3 -I "$JR/router_copilot.py" key > "$STAGE/key.txt" 2>&1; then
  cat "$STAGE/key.txt"
  cat <<'MSG'

NOTE: the active backend lacks a credential (see above), so the router cannot size messages. For TypeSafe, store the
key once (you are prompted for the value, so it stays out of shell history):
    security add-generic-password -U -a "$USER" -s TYPESAFE_API_KEY -w
For an Azure Decision-1 deployment, store MODEL_ROUTER_AZURE_ENDPOINT and MODEL_ROUTER_AZURE_DEPLOYMENT the same way and run `az login`.
MSG
fi

cat <<MSG

Next steps:
  1. Start Copilot CLI (copilot), or open a Copilot-harness chat in VS Code.
  2. Type:  model router on        (also: model router off | status | reset | model ...)
  Shell:    python3 -I "$JR/router_copilot.py" on|off|status|reset|model
  Models:   python3 -I "$JR/router_copilot.py" model <size> <model-id>    (or in chat: model router model <size> <model-id>)
            changes one size's model and re-renders its agent file in place; 'model' alone shows the table,
            'models' lists the models your account can use, grouped by the size they fit (chat: model router models).
            Your choices live in $JR/models.json and survive re-installs.
  Key:      python3 -I "$JR/router_copilot.py" key    (says where TYPESAFE_API_KEY was found, never its value)
  Remove:   ./uninstall.sh       (with the same COPILOT_HOME, if you set one)

Optional, not written by the installer:
  routercp (Tier 3): add the bin folder to PATH yourself, for example
    fish:      fish_add_path "$JR/bin"
    bash/zsh:  export PATH="$JR/bin:\$PATH"
  Use:      routercp "prompt"    or    routercp -i "prompt"
MSG

# The JSON snippets are built by python so that paths with spaces are escaped correctly.
python3 -I - "$JR" <<'PY'
import json, sys
jr = sys.argv[1]
print("\nstatusLine: paste into ~/.copilot/settings.json (top level):")
print(json.dumps({"statusLine": {"type": "command",
                                 "command": f'python3 -I "{jr}/router_statusline.py"'}}, indent=2))
PY

if [ "$TIER2" = 1 ]; then
  python3 -I - "$JR" <<'PY'
import json, sys
jr = sys.argv[1]
snippet = {"mcpServers": {"model-router": {"type": "local", "command": "python3",
                                         "args": ["-I", f"{jr}/router_mcp.py"], "tools": ["*"]}}}
print("\nTier 2 MCP server: merge this into ~/.copilot/mcp-config.json (keep your other servers):")
print(json.dumps(snippet, indent=2))
print("Use Tier 2 only if the userPromptTransformed hook (Tier 1) stops working: both would size each message.")
PY
fi
