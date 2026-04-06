#!/bin/bash
# Verify dotfiles installation is complete and correctly configured.
# Run after install.sh to confirm everything is wired up.
# Exit code 0 = all checks passed. Non-zero = failures found.

PASS=0
FAIL=0

ok()   { echo "  ✅ $1"; ((PASS++)); }
fail() { echo "  ❌ $1"; ((FAIL++)); }
warn() { echo "  ⚠️  $1"; }
section() { echo ""; echo "── $1"; }

# ============================================================================
# Local override files
# ============================================================================
section "Local override files"

if [[ -f "$HOME/.gitconfig.local" ]]; then
    email=$(git config --file "$HOME/.gitconfig.local" user.email 2>/dev/null)
    name=$(git config --file "$HOME/.gitconfig.local" user.name 2>/dev/null)
    if [[ -n "$email" && -n "$name" ]]; then
        ok ".gitconfig.local — $name <$email>"
    else
        fail ".gitconfig.local exists but missing name or email"
    fi
else
    fail "~/.gitconfig.local not found — git commits will have no author identity"
    echo "     Fix: printf '[user]\n\tname = Your Name\n\temail = you@email.com\n' > ~/.gitconfig.local"
fi

if [[ -f "$HOME/.bashrc.local" ]]; then
    ok "~/.bashrc.local exists"
    if grep -q "REPOS_DIR" "$HOME/.bashrc.local" 2>/dev/null; then
        repos_dir=$(bash -c 'source ~/.bashrc.local 2>/dev/null; echo "$REPOS_DIR"')
        ok "REPOS_DIR set to: $repos_dir"
    else
        warn "~/.bashrc.local exists but REPOS_DIR not set (ff/fcd will use ~/repos)"
    fi
else
    fail "~/.bashrc.local not found — machine-specific aliases not configured"
    echo "     Fix: touch ~/.bashrc.local and add REPOS_DIR and work aliases"
fi

# ============================================================================
# Shell files
# ============================================================================
section "Shell files"

for f in .bashrc .bash_profile .gitconfig; do
    if [[ -f "$HOME/$f" ]]; then
        ok "~/$f installed"
    else
        fail "~/$f not found — run: bash install.sh"
    fi
done

if [[ -f "$HOME/.config/starship.toml" ]]; then
    ok "~/.config/starship.toml installed"
else
    fail "~/.config/starship.toml not found — run: bash install.sh"
fi

# ============================================================================
# SSH configuration
# ============================================================================
section "SSH"

if [[ -f "$HOME/.ssh/config" ]]; then
    ok "~/.ssh/config exists"
else
    fail "~/.ssh/config not found — multi-account SSH not configured"
    echo "     See README.md → First-Time Setup → Configure SSH"
fi

# Test github-work
result=$(ssh -T git@github-work 2>&1)
if echo "$result" | grep -q "successfully authenticated"; then
    account=$(echo "$result" | grep -o 'Hi [^!]*' | sed 's/Hi //')
    ok "github-work → authenticated as: $account"
else
    fail "github-work SSH connection failed"
    echo "     Run: ssh -T git@github-work"
fi

# Test github-personal (optional — don't fail if not set up)
result=$(ssh -T git@github-personal 2>&1)
if echo "$result" | grep -q "successfully authenticated"; then
    account=$(echo "$result" | grep -o 'Hi [^!]*' | sed 's/Hi //')
    ok "github-personal → authenticated as: $account"
else
    warn "github-personal SSH not working (optional)"
fi

# ============================================================================
# Atlassian credentials
# ============================================================================
section "Atlassian credentials"

CREDS="$HOME/.atlassian/credentials"
if [[ -f "$CREDS" ]]; then
    ok "~/.atlassian/credentials exists"
    # Parse INI-style format (same as atlassian-common.sh)
    local_email="" local_token="" local_jira="" local_conf="" section=""
    while IFS='=' read -r key value; do
        key=$(echo "$key" | xargs); value=$(echo "$value" | xargs)
        [[ "$key" =~ ^#.*$ || -z "$key" ]] && continue
        [[ "$key" =~ ^\[.*\]$ ]] && section="$key" && continue
        if [[ "$section" == "[default]" ]]; then
            case "$key" in
                email)          local_email="$value" ;;
                api_token)      local_token="$value" ;;
                jira_url)       local_jira="$value"  ;;
                confluence_url) local_conf="$value"  ;;
            esac
        fi
    done < "$CREDS"
    [[ -n "$local_email" ]] && ok "  email: $local_email"    || fail "  email missing from credentials"
    [[ -n "$local_token" ]] && ok "  api_token set"          || fail "  api_token missing from credentials"
    [[ -n "$local_jira"  ]] && ok "  jira_url: $local_jira" || warn "  jira_url not set (required for Jira skill)"
    [[ -n "$local_conf"  ]] && ok "  confluence_url set"    || warn "  confluence_url not set (required for Confluence skill)"
else
    fail "~/.atlassian/credentials not found"
    echo "     Fix: bash ~/.claude/scripts/setup-credentials-interactive.sh"
fi

# ============================================================================
# Claude scripts and skills
# ============================================================================
section "Claude scripts"

CLAUDE_DIR="$HOME/.claude"
for script in jira-rest-api.sh confluence-rest-api.sh azure-devops-rest-api.sh atlassian-common.sh setup-credentials-interactive.sh; do
    if [[ -f "$CLAUDE_DIR/scripts/$script" ]]; then
        ok "$script"
    else
        fail "$script not found in ~/.claude/scripts/"
    fi
done

section "Claude skills"
for skill in jira confluence azure-devops; do
    if [[ -d "$CLAUDE_DIR/skills/$skill" ]]; then
        ok "$skill skill"
    else
        fail "$skill skill not found in ~/.claude/skills/"
    fi
done

# ============================================================================
# Windows Terminal
# ============================================================================
section "Windows Terminal"

WT_SETTINGS_FILE="$LOCALAPPDATA/Packages/Microsoft.WindowsTerminal_8wekyb3d8bbwe/LocalState/settings.json"
if [[ -f "$WT_SETTINGS_FILE" ]]; then
    scheme=$(python -m json.tool "$WT_SETTINGS_FILE" 2>/dev/null | grep '"colorScheme"' | head -1 | tr -d ' ",' | cut -d: -f2)
    font=$(python -m json.tool "$WT_SETTINGS_FILE" 2>/dev/null | grep '"face"' | head -1 | tr -d ' ",' | cut -d: -f2)
    ok "settings.json found (scheme: $scheme, font: $font)"
else
    warn "Windows Terminal settings.json not found (not installed?)"
fi

# ============================================================================
# Tools
# ============================================================================
section "CLI tools"

tools=(starship bat eza fzf rg fd zoxide atuin lazygit glow delta jq yq gh)
for tool in "${tools[@]}"; do
    if command -v "$tool" &>/dev/null; then
        ok "$tool"
    else
        fail "$tool not found — run: winget import winget-packages.json --ignore-unavailable"
    fi
done

# ============================================================================
# Summary
# ============================================================================
echo ""
echo "════════════════════════════════════════"
echo "  Passed: $PASS   Failed: $FAIL"
echo "════════════════════════════════════════"

if [[ $FAIL -gt 0 ]]; then
    echo "  Run 'bash install.sh' to fix missing files."
    echo "  See README.md for full setup steps."
    exit 1
else
    echo "  All checks passed. Setup is complete."
fi
