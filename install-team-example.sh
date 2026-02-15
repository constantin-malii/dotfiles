#!/bin/bash
# Example team install script for Symend claude-scripts
# This would live in the team repo: claude-scripts-symend/install.sh

set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="$HOME/.claude"

echo "Installing Symend Claude Scripts..."

# Create .claude directory if it doesn't exist
mkdir -p "$CLAUDE_DIR"/{skills,scripts}

# Symlink team skills
echo "Installing skills..."
ln -sf "$REPO_DIR/skills/jira-symend" "$CLAUDE_DIR/skills/jira-symend"
ln -sf "$REPO_DIR/skills/confluence-symend" "$CLAUDE_DIR/skills/confluence-symend"

# Optionally symlink shared scripts (if team maintains them)
# ln -sf "$REPO_DIR/scripts/jira-rest-api.sh" "$CLAUDE_DIR/scripts/jira-rest-api.sh"

echo "✅ Symend Claude Scripts installed!"
echo ""
echo "Location: $CLAUDE_DIR/skills/"
echo "  - jira-symend"
echo "  - confluence-symend"
echo ""
echo "To update: cd $REPO_DIR && git pull"
echo "To uninstall: rm $CLAUDE_DIR/skills/{jira-symend,confluence-symend}"
