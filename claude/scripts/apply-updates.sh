#!/bin/bash
# Apply updates found by check-updates.sh: winget, choco, and optionally
# Windows OS updates. Prompts for confirmation before each category.
#
# Usage: bash apply-updates.sh [--yes] [--os]
#   --yes   skip confirmation prompts (non-interactive)
#   --os    also install pending Windows Updates (requires elevation, may reboot)

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

section "System Restore point"
if command -v powershell.exe >/dev/null 2>&1; then
    powershell.exe -NoProfile -Command '
        $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
        if (-not $isAdmin) {
            Write-Output "  Skipped: requires an elevated (Run as Administrator) shell to create a restore point."
            Write-Output "  Proceeding WITHOUT a rollback point. Re-run elevated for a safety net."
        } else {
            try {
                Enable-ComputerRestore -Drive "C:\" -ErrorAction Stop
                Checkpoint-Computer -Description "Before updates-apply ($(Get-Date -Format s))" -RestorePointType "MODIFY_SETTINGS" -ErrorAction Stop
                Write-Output "  Restore point created. To roll back: rstrui.exe, or Restore-Computer -RestorePoint <seq>"
            } catch {
                Write-Output "  Could not create a restore point: $($_.Exception.Message)"
                Write-Output "  Proceeding WITHOUT a rollback point."
            }
        }
    ' 2>&1 | sed 's/\r$//'
else
    echo "  powershell.exe not found; proceeding without a rollback point."
fi

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
                $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
                if (-not $isAdmin) {
                    Write-Output "  Skipped: requires an elevated (Run as Administrator) shell."
                } elseif (Get-Module -ListAvailable -Name PSWindowsUpdate) {
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

echo ""
echo "Done. Re-run 'updates' to confirm what's left outstanding."
