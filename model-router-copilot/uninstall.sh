#!/usr/bin/env bash
# Remove what install.sh added from ${COPILOT_HOME:-$HOME/.copilot}: the hook files (Tier 1 and Tier 2), the four
# helper agents, the model-router skill, and the model-router directory (router core, adapter, status line, routercp,
# the Tier 2 MCP server, the agent templates, models.json, state.json and decisions.log with the stats). Empty folders that install.sh created are
# removed. Other Copilot files are not touched. Backups (*.bak-<timestamp>) are listed, not deleted.
set -euo pipefail

CP="${COPILOT_HOME:-$HOME/.copilot}"
JR="$CP/model-router"

rm -f "$CP/hooks/model-router.json" "$CP/hooks/model-router-session.json" \
      "$CP/hooks/jev-router.json" "$CP/hooks/jev-router-session.json"  # the last two: the name before the rename
for size in tiny everyday large hardest; do
  rm -f "$CP/agents/router-$size.agent.md" "$CP/agents/jev-$size.agent.md"
done
rm -rf "$CP/skills/model-router" "$CP/skills/jev-router"
rm -rf "$JR" "$CP/jev-router"
rmdir "$CP/skills" "$CP/hooks" "$CP/agents" 2>/dev/null || true  # only removes empty folders

echo "Model router removed from $CP (hook files, helper agents, skill, and $JR with its models.json, state and stats)."
backups="$(find "$CP/agents" "$CP/hooks" -maxdepth 1 \( -name 'router-*.bak-*' -o -name 'model-router*.json.bak-*' \) 2>/dev/null || true)"
if [ -n "$backups" ]; then
  echo "Backups made by install.sh were kept. Delete them yourself if you no longer need them:"
  echo "$backups"
fi
# install.sh never writes these two files, so remove the entries yourself if you pasted them.
if [ -f "$CP/mcp-config.json" ] && grep -q "router_mcp.py" "$CP/mcp-config.json"; then
  echo "Remove the model-router entry from $CP/mcp-config.json yourself (the Tier 2 MCP server)."
fi
if [ -f "$CP/settings.json" ] && grep -q "router_statusline.py" "$CP/settings.json"; then
  echo "Remove the statusLine entry from $CP/settings.json yourself (it points at router_statusline.py)."
fi
