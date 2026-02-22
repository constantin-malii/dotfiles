#!/bin/bash
# Smart install/update script for Claude Scripts
# Handles both initial install and updates
#
# Usage:
#   bash install.sh                    # Install all skills and scripts
#   bash install.sh --only jira        # Install only the jira skill + its scripts
#   bash install.sh --only azure-devops # Install only the azure-devops skill + its scripts
#   bash install.sh --list             # List available skills

set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
BACKUP_DIR="$CLAUDE_DIR/.backup-$(date +%Y%m%d-%H%M%S)"

# Parse arguments
ONLY_SKILL=""
if [[ "$1" == "--only" ]]; then
    ONLY_SKILL="$2"
    if [[ -z "$ONLY_SKILL" ]]; then
        echo "ERROR: --only requires a skill name" >&2
        echo "Usage: bash install.sh --only <skill-name>" >&2
        echo "Run 'bash install.sh --list' to see available skills" >&2
        exit 1
    fi
    if [[ ! -d "$REPO_DIR/claude/skills/$ONLY_SKILL" ]]; then
        echo "ERROR: Skill '$ONLY_SKILL' not found in $REPO_DIR/claude/skills/" >&2
        echo "Run 'bash install.sh --list' to see available skills" >&2
        exit 1
    fi
elif [[ "$1" == "--list" ]]; then
    echo "Available skills:"
    for skill_dir in "$REPO_DIR/claude/skills"/*/; do
        skill_name=$(basename "$skill_dir")
        desc=$(sed -n 's/^description: *//p' "$skill_dir/SKILL.md" 2>/dev/null | head -1)
        echo "  $skill_name - $desc"
    done
    exit 0
elif [[ -n "$1" ]]; then
    echo "ERROR: Unknown option '$1'" >&2
    echo "Usage: bash install.sh [--only <skill>] [--list]" >&2
    exit 1
fi

# Skill-to-script mapping: which scripts each skill needs
declare -A SKILL_SCRIPTS
SKILL_SCRIPTS[jira]="jira-rest-api.sh atlassian-common.sh create-issue-link.sh delete-issue-link.sh get-issue-links.sh setup-credentials-interactive.sh ATLASSIAN_SETUP.md"
SKILL_SCRIPTS[confluence]="confluence-rest-api.sh atlassian-common.sh setup-credentials-interactive.sh ATLASSIAN_SETUP.md"
SKILL_SCRIPTS[azure-devops]="azure-devops-rest-api.sh"

# Detect if this is initial install or update
if [[ -d "$CLAUDE_DIR/scripts" ]] || [[ -d "$CLAUDE_DIR/skills" ]]; then
    MODE="update"
else
    MODE="install"
fi

echo "=========================================="
if [[ -n "$ONLY_SKILL" ]]; then
    echo "Installing skill: $ONLY_SKILL"
else
    if [[ "$MODE" == "install" ]]; then
        echo "Installing Claude Scripts (first time)"
    else
        echo "Updating Claude Scripts"
    fi
fi
echo "=========================================="
echo ""

# Create directory structure
mkdir -p "$CLAUDE_DIR"/{skills,scripts}

# Backup existing files on update
if [[ "$MODE" == "update" ]] && [[ -z "$ONLY_SKILL" ]]; then
    echo "Creating backup: $BACKUP_DIR"
    mkdir -p "$BACKUP_DIR"
    [[ -d "$CLAUDE_DIR/scripts" ]] && cp -r "$CLAUDE_DIR/scripts" "$BACKUP_DIR/"
    [[ -d "$CLAUDE_DIR/skills" ]] && cp -r "$CLAUDE_DIR/skills" "$BACKUP_DIR/"
    echo "Backup created"
    echo ""
fi

if [[ -n "$ONLY_SKILL" ]]; then
    # Install single skill + its required scripts
    echo "-> Copying skill: $ONLY_SKILL..."
    mkdir -p "$CLAUDE_DIR/skills/$ONLY_SKILL"
    cp -r "$REPO_DIR/claude/skills/$ONLY_SKILL/"* "$CLAUDE_DIR/skills/$ONLY_SKILL/"

    scripts="${SKILL_SCRIPTS[$ONLY_SKILL]:-}"
    if [[ -n "$scripts" ]]; then
        echo "-> Copying scripts for $ONLY_SKILL..."
        for script in $scripts; do
            if [[ -f "$REPO_DIR/claude/scripts/$script" ]]; then
                cp "$REPO_DIR/claude/scripts/$script" "$CLAUDE_DIR/scripts/"
                [[ "$script" == *.sh ]] && chmod +x "$CLAUDE_DIR/scripts/$script"
            fi
        done
    fi

    # Copy atlassian templates if this skill needs atlassian-common.sh
    if echo "$scripts" | grep -q "atlassian-common.sh"; then
        mkdir -p "$CLAUDE_DIR/atlassian"
        if [[ -f "$REPO_DIR/claude/atlassian/credentials.template" ]]; then
            cp "$REPO_DIR/claude/atlassian/credentials.template" "$CLAUDE_DIR/atlassian/"
        fi
        if [[ -f "$CLAUDE_DIR/atlassian/credentials" ]]; then
            echo "Preserved existing credentials file (not overwritten)"
        fi
    fi
else
    # Install everything
    echo "-> Copying scripts..."
    cp -r "$REPO_DIR/claude/scripts/"*.sh "$CLAUDE_DIR/scripts/" 2>/dev/null || true
    cp -r "$REPO_DIR/claude/scripts/"*.md "$CLAUDE_DIR/scripts/" 2>/dev/null || true
    chmod +x "$CLAUDE_DIR/scripts/"*.sh 2>/dev/null || true

    echo "-> Copying skills..."
    rsync -a --delete "$REPO_DIR/claude/skills/" "$CLAUDE_DIR/skills/" 2>/dev/null || \
        cp -r "$REPO_DIR/claude/skills/"* "$CLAUDE_DIR/skills/" 2>/dev/null || true

    echo "-> Copying templates..."
    mkdir -p "$CLAUDE_DIR/atlassian"
    if [[ -f "$REPO_DIR/claude/atlassian/credentials.template" ]]; then
        cp "$REPO_DIR/claude/atlassian/credentials.template" "$CLAUDE_DIR/atlassian/"
    fi
    if [[ -f "$CLAUDE_DIR/atlassian/credentials" ]]; then
        echo "Preserved existing credentials file (not overwritten)"
    fi
fi

echo ""
echo "=========================================="
if [[ -n "$ONLY_SKILL" ]]; then
    echo "Skill '$ONLY_SKILL' installed!"
    echo ""
    echo "Test: bash $CLAUDE_DIR/scripts/${ONLY_SKILL}-rest-api.sh 2>&1 | head -5"
elif [[ "$MODE" == "install" ]]; then
    echo "Installation complete!"
    echo ""
    echo "Next steps:"
    echo "1. Setup credentials: $CLAUDE_DIR/scripts/ATLASSIAN_SETUP.md"
    echo "2. Test: bash $CLAUDE_DIR/scripts/jira-rest-api.sh mine"
else
    echo "Update complete!"
    echo ""
    echo "Backup saved to: $BACKUP_DIR"
    echo "To restore: cp -r $BACKUP_DIR/* $CLAUDE_DIR/"
fi
echo "=========================================="
