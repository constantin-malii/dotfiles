#!/bin/bash
# Smart install/update script for Claude Scripts
# Handles both initial install and updates

set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
BACKUP_DIR="$CLAUDE_DIR/.backup-$(date +%Y%m%d-%H%M%S)"

# Detect if this is initial install or update
if [[ -d "$CLAUDE_DIR/scripts" ]] || [[ -d "$CLAUDE_DIR/skills" ]]; then
    MODE="update"
else
    MODE="install"
fi

echo "=========================================="
if [[ "$MODE" == "install" ]]; then
    echo "Installing Claude Scripts (first time)"
else
    echo "Updating Claude Scripts"
fi
echo "=========================================="
echo ""

# Create directory structure
mkdir -p "$CLAUDE_DIR"/{skills,scripts,atlassian}

# Backup existing files on update
if [[ "$MODE" == "update" ]]; then
    echo "Creating backup: $BACKUP_DIR"
    mkdir -p "$BACKUP_DIR"

    # Backup only if files exist
    [[ -d "$CLAUDE_DIR/scripts" ]] && cp -r "$CLAUDE_DIR/scripts" "$BACKUP_DIR/"
    [[ -d "$CLAUDE_DIR/skills" ]] && cp -r "$CLAUDE_DIR/skills" "$BACKUP_DIR/"

    echo "✅ Backup created"
    echo ""
fi

# Copy scripts (preserves executable bit)
echo "→ Copying scripts..."
cp -r "$REPO_DIR/claude/scripts/"*.sh "$CLAUDE_DIR/scripts/" 2>/dev/null || true
cp -r "$REPO_DIR/claude/scripts/"*.md "$CLAUDE_DIR/scripts/" 2>/dev/null || true
chmod +x "$CLAUDE_DIR/scripts/"*.sh 2>/dev/null || true

# Copy skills
echo "→ Copying skills..."
rsync -a --delete "$REPO_DIR/claude/skills/" "$CLAUDE_DIR/skills/" 2>/dev/null || \
    cp -r "$REPO_DIR/claude/skills/"* "$CLAUDE_DIR/skills/" 2>/dev/null || true

# Copy templates (never overwrite actual credentials!)
echo "→ Copying templates..."
if [[ -f "$REPO_DIR/claude/atlassian/credentials.template" ]]; then
    cp "$REPO_DIR/claude/atlassian/credentials.template" "$CLAUDE_DIR/atlassian/"
fi

# Never overwrite actual credentials
if [[ -f "$CLAUDE_DIR/atlassian/credentials" ]]; then
    echo "⚠️  Preserved existing credentials file (not overwritten)"
fi

echo ""
echo "=========================================="
if [[ "$MODE" == "install" ]]; then
    echo "✅ Installation complete!"
    echo ""
    echo "Next steps:"
    echo "1. Setup credentials: $CLAUDE_DIR/scripts/ATLASSIAN_SETUP.md"
    echo "2. Test: bash $CLAUDE_DIR/scripts/jira-rest-api.sh mine"
else
    echo "✅ Update complete!"
    echo ""
    echo "Backup saved to: $BACKUP_DIR"
    echo "To restore: cp -r $BACKUP_DIR/* $CLAUDE_DIR/"
fi
echo "=========================================="
