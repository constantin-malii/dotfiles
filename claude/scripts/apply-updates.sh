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
# Git.Git can never be upgraded from this script, or from any window while
# Claude Code is running (it keeps bash/ssh-agent processes alive in the
# background). See docs/check-updates.md for the manual upgrade steps.
#
# Usage: bash apply-updates.sh [--yes] [--os]
#   --yes   skip confirmation prompts (non-interactive)
#   --os    also install pending Windows Updates (only runs if elevated, may reboot)

set -uo pipefail

YES=false
DO_OS=false
for arg in "$@"; do
    case "$arg" in
        --yes) YES=true ;;
        --os) DO_OS=true ;;
    esac
done

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
    echo "  Claude Code is running). See docs/check-updates.md for how to upgrade Git."

    section "Windows OS updates"
    if $DO_OS; then
        echo "  Skipped: requires an elevated shell. Re-run this script elevated with --os."
    else
        echo "  Skipped (run elevated with --os to install Windows Updates)."
    fi
fi

echo ""
echo "Done. Re-run 'updates' to confirm what's left outstanding."
