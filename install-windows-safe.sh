#!/bin/bash
# Windows-safe install script (copy instead of symlink)
# Works on all platforms without symlink support

set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="$HOME/.claude"

echo "Installing Claude Scripts (copy mode)..."

# Create .claude directory structure
mkdir -p "$CLAUDE_DIR"/{skills,scripts,atlassian}

# Copy scripts (preserves executable bit)
echo "Copying scripts..."
cp -r "$REPO_DIR/claude/scripts/"* "$CLAUDE_DIR/scripts/"
chmod +x "$CLAUDE_DIR/scripts/"*.sh

# Copy skills
echo "Copying skills..."
cp -r "$REPO_DIR/claude/skills/"* "$CLAUDE_DIR/skills/"

# Copy templates
echo "Copying templates..."
cp "$REPO_DIR/claude/atlassian/credentials.template" "$CLAUDE_DIR/atlassian/"

echo "✅ Claude Scripts installed!"
echo ""
echo "Files copied to: $CLAUDE_DIR"
echo ""
echo "To update:"
echo "  cd $REPO_DIR && git pull && ./install-windows-safe.sh"
