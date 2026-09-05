#!/bin/bash
# Apply updates found by check-updates.sh: winget, choco, and optionally
# Windows OS updates. Prompts for confirmation before each category.
#
# Winget upgrades of user-scope packages fail when run elevated ("cannot be
# uninstalled when running with administrator privileges"). Choco and Windows
# Update both require elevation to do anything useful. So this script splits
# by elevation state:
#   - non-elevated: does winget (excluding Git, see note below), skips choco + OS updates
#   - elevated:     does choco + OS updates (if --os), skips winget
#
# Git.Git and the Claude desktop app can both get stuck mid-upgrade because
# their own installer can't replace files while a matching process is
# running — Git while any bash/Claude Code session is open, the desktop app
# while it's open itself. See docs/check-updates.md, or use --defer-git /
# --defer-claude to queue a background watcher that finishes the upgrade
# once the blocking process(es) exit.
#
# Usage: bash apply-updates.sh [--yes] [--os] [--defer-git] [--defer-claude]
#   --yes            skip confirmation prompts (non-interactive)
#   --os             also install pending Windows Updates (only runs if elevated, may reboot)
#   --defer-git      queue a detached watcher that upgrades Git once all bash/claude
#                    processes exit (i.e. once you close every terminal, including this one)
#   --defer-claude   queue a detached watcher that upgrades the Claude desktop app
#                    once it's closed (does not require closing Claude Code)

set -uo pipefail

YES=false
DO_OS=false
DEFER_GIT=false
DEFER_CLAUDE=false
for arg in "$@"; do
    case "$arg" in
        --yes) YES=true ;;
        --os) DO_OS=true ;;
        --defer-git) DEFER_GIT=true ;;
        --defer-claude) DEFER_CLAUDE=true ;;
    esac
done

queue_watcher() {
    local winget_id="$1" target="$2" log_name="$3" label="$4"
    if ! command -v powershell.exe >/dev/null 2>&1; then
        echo "  powershell.exe not found; cannot queue watcher."
        return
    fi
    local script_dir watcher_ps1_win log_dir log_win
    script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
    watcher_ps1_win=$(cygpath -w "$script_dir/winget-upgrade-watcher.ps1" 2>/dev/null || echo "$script_dir/winget-upgrade-watcher.ps1")
    log_dir="$HOME/.claude/logs"
    mkdir -p "$log_dir"
    log_win=$(cygpath -w "$log_dir/$log_name" 2>/dev/null || echo "$log_dir/$log_name")
    powershell.exe -NoProfile -Command "Start-Process powershell -WindowStyle Hidden -ArgumentList '-NoProfile','-ExecutionPolicy','Bypass','-File','$watcher_ps1_win','-LogPath','$log_win','-WingetId','$winget_id','-Target','$target'" 2>&1 | sed 's/\r$//'
    echo "  Watcher queued. $label"
    echo "  Check progress: cat ~/.claude/logs/$log_name"
}

confirm() {
    $YES && return 0
    read -r -p "$1 [y/N] " reply
    [[ "$reply" =~ ^[Yy]$ ]]
}

section() {
    echo ""
    echo "== $1 =="
}

IS_ADMIN=false
if command -v powershell.exe >/dev/null 2>&1; then
    admin_check=$(powershell.exe -NoProfile -Command '
        ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
    ' 2>/dev/null | tr -d '\r\n')
    [[ "$admin_check" == "True" ]] && IS_ADMIN=true
fi

section "System Restore point"
if command -v powershell.exe >/dev/null 2>&1; then
    if $IS_ADMIN; then
        powershell.exe -NoProfile -Command '
            try {
                Enable-ComputerRestore -Drive "C:\" -ErrorAction Stop
                Checkpoint-Computer -Description "Before updates-apply ($(Get-Date -Format s))" -RestorePointType "MODIFY_SETTINGS" -ErrorAction Stop
                Write-Output "  Restore point created. To roll back: rstrui.exe, or Restore-Computer -RestorePoint <seq>"
            } catch {
                Write-Output "  Could not create a restore point: $($_.Exception.Message)"
                Write-Output "  Proceeding WITHOUT a rollback point."
            }
        ' 2>&1 | sed 's/\r$//'
    else
        echo "  Skipped: requires an elevated (Run as Administrator) shell to create a restore point."
        echo "  Proceeding WITHOUT a rollback point. Re-run elevated for a safety net."
    fi
else
    echo "  powershell.exe not found; proceeding without a rollback point."
fi

if $IS_ADMIN; then
    echo ""
    echo "Running elevated: skipping winget (user-scope packages fail to upgrade"
    echo "when elevated). Re-run this script WITHOUT elevation for those."

    section "Chocolatey apps"
    if command -v powershell.exe >/dev/null 2>&1; then
        if confirm "Run 'choco upgrade all -y'?"; then
            powershell.exe -NoProfile -Command 'choco upgrade all -y' 2>&1 | sed 's/\r$//'
        else
            echo "  Skipped."
        fi
    else
        echo "  powershell.exe not found"
    fi

    if $DO_OS; then
        section "Windows OS updates"
        if command -v powershell.exe >/dev/null 2>&1; then
            if confirm "Install pending Windows Updates now? (may require reboot)"; then
                powershell.exe -NoProfile -Command '
                    if (Get-Module -ListAvailable -Name PSWindowsUpdate) {
                        Import-Module PSWindowsUpdate
                        Install-WindowsUpdate -MicrosoftUpdate -AcceptAll -IgnoreReboot -Verbose
                    } else {
                        Write-Output "  PSWindowsUpdate module not installed. Install with:"
                        Write-Output "    Install-Module PSWindowsUpdate -Scope CurrentUser -Force"
                    }
                ' 2>&1 | sed 's/\r$//'
            else
                echo "  Skipped."
            fi
        else
            echo "  powershell.exe not found"
        fi
    else
        section "Windows OS updates"
        echo "  Skipped (pass --os to install Windows Updates too)."
    fi
else
    section "Winget apps"
    if command -v powershell.exe >/dev/null 2>&1; then
        if confirm "Run 'winget upgrade --all'?"; then
            powershell.exe -NoProfile -Command 'winget upgrade --all --include-unknown --accept-source-agreements --accept-package-agreements' 2>&1 | sed 's/\r$//'
        else
            echo "  Skipped."
        fi
    else
        echo "  powershell.exe not found"
    fi
    echo "  Note: Git.Git will always fail here (and even outside this script while"
    echo "  Claude Code is running). See docs/check-updates.md for how to upgrade Git,"
    echo "  or re-run with --defer-git to queue a background watcher for it."
    echo "  Note: Anthropic.Claude (the desktop app) will fail here if it's currently"
    echo "  open. Close it and re-run, or use --defer-claude to queue a watcher."

    if $DEFER_GIT; then
        section "Git upgrade (deferred)"
        queue_watcher "Git.Git" "bash-claude" "git-upgrade-watcher.log" \
            "It will upgrade Git once every bash/claude process on this machine exits (close all terminals, including this one)."
    fi

    if $DEFER_CLAUDE; then
        section "Claude desktop upgrade (deferred)"
        queue_watcher "Anthropic.Claude" "claude-desktop" "claude-desktop-upgrade-watcher.log" \
            "It will upgrade the Claude desktop app once it's closed (does NOT require closing Claude Code)."
    fi

    section "Windows OS updates"
    if $DO_OS; then
        echo "  Skipped: requires an elevated shell. Re-run this script elevated with --os."
    else
        echo "  Skipped (run elevated with --os to install Windows Updates)."
    fi
fi

echo ""
echo "Done. Re-run 'updates' to confirm what's left outstanding."
