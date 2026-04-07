#!/bin/bash
# Smart install/update script for dotfiles
# Handles both initial install and updates
#
# Usage:
#   bash install.sh                    # Install everything (shell + config + claude)
#   bash install.sh --claude           # Only Claude Code files (skills, commands, agents, scripts)
#   bash install.sh --shell            # Only shell configs (.bash_profile, .gitconfig, starship)
#   bash install.sh --config           # Only tool configs (lazygit, lazydocker, terminal)
#   bash install.sh --only jira        # Only the jira skill + its scripts
#   bash install.sh --list             # List available skills

set -e

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CLAUDE_DIR="$HOME/.claude"
BACKUP_DIR="$CLAUDE_DIR/.backup-$(date +%Y%m%d-%H%M%S)"

# Parse arguments
RUN_CLAUDE=false
RUN_SHELL=false
RUN_CONFIG=false
ONLY_SKILL=""

if [[ "$1" == "--only" ]]; then
    RUN_CLAUDE=true
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
elif [[ "$1" == "--claude" ]]; then
    RUN_CLAUDE=true
elif [[ "$1" == "--shell" ]]; then
    RUN_SHELL=true
elif [[ "$1" == "--config" ]]; then
    RUN_CONFIG=true
elif [[ -z "$1" ]]; then
    RUN_CLAUDE=true
    RUN_SHELL=true
    RUN_CONFIG=true
else
    echo "ERROR: Unknown option '$1'" >&2
    echo "Usage: bash install.sh [--claude | --shell | --config | --only <skill> | --list]" >&2
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
elif [[ "$RUN_CLAUDE" == true ]] && [[ "$RUN_SHELL" == false ]] && [[ "$RUN_CONFIG" == false ]]; then
    echo "Installing Claude Code files only"
elif [[ "$RUN_SHELL" == true ]] && [[ "$RUN_CLAUDE" == false ]] && [[ "$RUN_CONFIG" == false ]]; then
    echo "Installing shell configs only"
elif [[ "$RUN_CONFIG" == true ]] && [[ "$RUN_CLAUDE" == false ]] && [[ "$RUN_SHELL" == false ]]; then
    echo "Installing tool configs only"
elif [[ "$MODE" == "install" ]]; then
    echo "Installing dotfiles (first time)"
else
    echo "Updating dotfiles"
fi
echo "=========================================="
echo ""

# Create base directory structure
mkdir -p "$CLAUDE_DIR"/{skills,scripts,atlassian}
mkdir -p "$HOME/.config"

# Backup on full update only
if [[ "$MODE" == "update" ]] && [[ "$RUN_CLAUDE" == true ]] && [[ "$RUN_SHELL" == true ]] && [[ "$RUN_CONFIG" == true ]] && [[ -z "$ONLY_SKILL" ]]; then
    echo "Creating backup: $BACKUP_DIR"
    mkdir -p "$BACKUP_DIR"
    [[ -d "$CLAUDE_DIR/scripts" ]] && cp -r "$CLAUDE_DIR/scripts" "$BACKUP_DIR/"
    [[ -d "$CLAUDE_DIR/skills" ]] && cp -r "$CLAUDE_DIR/skills" "$BACKUP_DIR/"
    for f in .bashrc .bash_profile .gitconfig; do
        [[ -f "$HOME/$f" ]] && cp "$HOME/$f" "$BACKUP_DIR/$f"
    done
    [[ -f "$HOME/.config/starship.toml" ]] && cp "$HOME/.config/starship.toml" "$BACKUP_DIR/starship.toml"
    echo "✅ Backup created"
    echo ""
fi

# ── Claude Code files ──────────────────────────────────────────────────────────
if [[ "$RUN_CLAUDE" == true ]]; then
    if [[ -n "$ONLY_SKILL" ]]; then
        # Single skill + its required scripts
        echo "→ Copying skill: $ONLY_SKILL..."
        mkdir -p "$CLAUDE_DIR/skills/$ONLY_SKILL"
        cp -r "$REPO_DIR/claude/skills/$ONLY_SKILL/"* "$CLAUDE_DIR/skills/$ONLY_SKILL/"

        scripts="${SKILL_SCRIPTS[$ONLY_SKILL]:-}"
        if [[ -n "$scripts" ]]; then
            echo "→ Copying scripts for $ONLY_SKILL..."
            for script in $scripts; do
                if [[ -f "$REPO_DIR/claude/scripts/$script" ]]; then
                    cp "$REPO_DIR/claude/scripts/$script" "$CLAUDE_DIR/scripts/"
                    [[ "$script" == *.sh ]] && chmod +x "$CLAUDE_DIR/scripts/$script"
                fi
            done
        fi

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
        echo "→ Copying scripts..."
        cp -r "$REPO_DIR/claude/scripts/"*.sh "$CLAUDE_DIR/scripts/" 2>/dev/null || true
        cp -r "$REPO_DIR/claude/scripts/"*.py "$CLAUDE_DIR/scripts/" 2>/dev/null || true
        cp -r "$REPO_DIR/claude/scripts/"*.md "$CLAUDE_DIR/scripts/" 2>/dev/null || true
        chmod +x "$CLAUDE_DIR/scripts/"*.sh 2>/dev/null || true
        chmod +x "$CLAUDE_DIR/scripts/"*.py 2>/dev/null || true

        echo "→ Copying skills..."
        rsync -a --delete "$REPO_DIR/claude/skills/" "$CLAUDE_DIR/skills/" 2>/dev/null || \
            cp -r "$REPO_DIR/claude/skills/"* "$CLAUDE_DIR/skills/" 2>/dev/null || true

        echo "→ Copying agents..."
        mkdir -p "$CLAUDE_DIR/agents"
        rsync -a --delete --exclude='.gitkeep' "$REPO_DIR/claude/agents/" "$CLAUDE_DIR/agents/" 2>/dev/null || \
            cp -r "$REPO_DIR/claude/agents/"* "$CLAUDE_DIR/agents/" 2>/dev/null || true

        echo "→ Copying commands..."
        mkdir -p "$CLAUDE_DIR/commands"
        rsync -a --delete --exclude='.gitkeep' "$REPO_DIR/claude/commands/" "$CLAUDE_DIR/commands/" 2>/dev/null || \
            cp -r "$REPO_DIR/claude/commands/"* "$CLAUDE_DIR/commands/" 2>/dev/null || true

        echo "→ Copying templates..."
        mkdir -p "$CLAUDE_DIR/atlassian"
        if [[ -f "$REPO_DIR/claude/atlassian/credentials.template" ]]; then
            cp "$REPO_DIR/claude/atlassian/credentials.template" "$CLAUDE_DIR/atlassian/"
        fi
        if [[ -f "$CLAUDE_DIR/atlassian/credentials" ]]; then
            echo "⚠️  Preserved existing credentials file (not overwritten)"
        fi
    fi
fi

# ── Tool configs ───────────────────────────────────────────────────────────────
if [[ "$RUN_CONFIG" == true ]]; then
    if [[ -d "$REPO_DIR/config" ]]; then
        echo "→ Copying tool configs..."
        mkdir -p "$HOME/.config/lazygit" "$HOME/.config/lazydocker"
        [[ -f "$REPO_DIR/config/lazygit.yml" ]]    && cp "$REPO_DIR/config/lazygit.yml"    "$HOME/.config/lazygit/config.yml"
        [[ -f "$REPO_DIR/config/lazydocker.yml" ]] && cp "$REPO_DIR/config/lazydocker.yml" "$HOME/.config/lazydocker/config.yml"
    fi

    WT_DIR="$LOCALAPPDATA/Packages/Microsoft.WindowsTerminal_8wekyb3d8bbwe/LocalState"
    if [[ -f "$REPO_DIR/windows/terminal-settings.json" ]] && [[ -d "$WT_DIR" ]]; then
        echo "→ Copying Windows Terminal settings..."
        cp "$REPO_DIR/windows/terminal-settings.json" "$WT_DIR/settings.json"
    fi
fi

# ── Shell configs ──────────────────────────────────────────────────────────────
if [[ "$RUN_SHELL" == true ]]; then
    if [[ -d "$REPO_DIR/shell" ]]; then
        echo "→ Copying shell configs..."
        [[ -f "$REPO_DIR/shell/.bashrc" ]]       && cp "$REPO_DIR/shell/.bashrc"       "$HOME/.bashrc"
        [[ -f "$REPO_DIR/shell/.bash_profile" ]] && cp "$REPO_DIR/shell/.bash_profile" "$HOME/.bash_profile"
        [[ -f "$REPO_DIR/shell/.gitconfig" ]]    && cp "$REPO_DIR/shell/.gitconfig"    "$HOME/.gitconfig"
        [[ -f "$REPO_DIR/shell/starship.toml" ]] && cp "$REPO_DIR/shell/starship.toml" "$HOME/.config/starship.toml"
    fi

    echo ""
    echo "→ Checking local overrides..."
    if [[ ! -f "$HOME/.bashrc.local" ]]; then
        echo "⚠️  ~/.bashrc.local not found — create it for machine-specific aliases/paths"
    fi
    if [[ ! -f "$HOME/.gitconfig.local" ]]; then
        echo "⚠️  ~/.gitconfig.local not found — git commits will have no author identity"
        echo "   Create it with:"
        echo "   printf '[user]\n\tname = Your Name\n\temail = you@example.com\n' > ~/.gitconfig.local"
    fi
fi

echo ""
echo "=========================================="
if [[ -n "$ONLY_SKILL" ]]; then
    echo "Skill '$ONLY_SKILL' installed!"
    echo ""
    echo "Test: bash $CLAUDE_DIR/scripts/${ONLY_SKILL}-rest-api.sh 2>&1 | head -5"
elif [[ "$RUN_CLAUDE" == true ]] && [[ "$RUN_SHELL" == false ]] && [[ "$RUN_CONFIG" == false ]]; then
    echo "Claude Code files installed!"
elif [[ "$RUN_SHELL" == true ]] && [[ "$RUN_CLAUDE" == false ]] && [[ "$RUN_CONFIG" == false ]]; then
    echo "Shell configs installed! Run: source ~/.bash_profile"
elif [[ "$RUN_CONFIG" == true ]] && [[ "$RUN_CLAUDE" == false ]] && [[ "$RUN_SHELL" == false ]]; then
    echo "Tool configs installed!"
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
