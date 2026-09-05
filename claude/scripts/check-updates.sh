#!/bin/bash
# Unified update check: winget apps, choco apps, Windows OS updates,
# Claude Code plugins, and manually-installed apps winget doesn't recognize.
#
# Usage: bash check-updates.sh [--full]
#   --full   also list installed apps that winget doesn't track (slower)

set -uo pipefail

FULL=false
[[ "${1:-}" == "--full" ]] && FULL=true

section() {
    echo ""
    echo "== $1 =="
}

section "Winget apps"
if command -v powershell.exe >/dev/null 2>&1; then
    powershell.exe -NoProfile -Command 'winget upgrade --include-unknown' 2>&1 | sed 's/\r$//'
else
    echo "  powershell.exe not found"
fi

section "Chocolatey apps"
if command -v powershell.exe >/dev/null 2>&1; then
    powershell.exe -NoProfile -Command 'choco outdated' 2>&1 | sed 's/\r$//'
else
    echo "  powershell.exe not found"
fi

section "Windows OS updates"
if command -v powershell.exe >/dev/null 2>&1; then
    powershell.exe -NoProfile -Command '
        $isAdmin = ([Security.Principal.WindowsPrincipal][Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole]::Administrator)
        if (-not $isAdmin) {
            Write-Output "  Skipped: requires an elevated (Run as Administrator) shell."
        } elseif (Get-Module -ListAvailable -Name PSWindowsUpdate) {
            Import-Module PSWindowsUpdate
            $updates = Get-WindowsUpdate -MicrosoftUpdate -ErrorAction Stop
            if ($updates) { $updates | Format-Table -AutoSize KB, Size, Title }
            else { Write-Output "  No pending updates found." }
        } else {
            Write-Output "  PSWindowsUpdate module not installed. Install with:"
            Write-Output "    Install-Module PSWindowsUpdate -Scope CurrentUser -Force"
        }
    ' 2>&1 | sed 's/\r$//'
else
    echo "  powershell.exe not found"
fi

section "Claude Code plugins"
if command -v claude >/dev/null 2>&1; then
    claude plugin marketplace update >/dev/null 2>&1
    if command -v jq >/dev/null 2>&1; then
        claude plugin list --json --available 2>/dev/null | jq -r '
            (.installed // (if type == "array" then . else [] end)) as $installed |
            (.available // []) as $available |
            ($available | map({(.name): .}) | add // {}) as $avail_by_name |
            [ $installed[] |
              select(.name as $n | $avail_by_name[$n]?) |
              . as $p |
              $avail_by_name[$p.name] as $a |
              select($a.version and $p.version and $a.version != $p.version) |
              "  \(.name): \(.version) -> \($a.version)"
            ] as $diffs |
            if ($diffs | length) > 0 then $diffs[] else "  All plugins up to date (or version info unavailable)." end
        ' 2>/dev/null || echo "  (could not parse plugin list; run: claude plugin list --json --available)"
    else
        echo "  jq not found; run: claude plugin list --json --available"
    fi
else
    echo "  claude CLI not found"
fi

if $FULL; then
    section "Installed apps winget does NOT recognize (manual review)"
    if command -v powershell.exe >/dev/null 2>&1; then
        powershell.exe -NoProfile -Command '
            $installed = Get-ItemProperty HKLM:\Software\Wow6432Node\Microsoft\Windows\CurrentVersion\Uninstall\*, HKLM:\Software\Microsoft\Windows\CurrentVersion\Uninstall\*, HKCU:\Software\Microsoft\Windows\CurrentVersion\Uninstall\* -ErrorAction SilentlyContinue |
                Where-Object { $_.DisplayName -and -not $_.SystemComponent } |
                Select-Object -ExpandProperty DisplayName -Unique | Sort-Object

            $wingetList = winget list --accept-source-agreements 2>$null
            $unmatched = $installed | Where-Object {
                $name = $_
                -not ($wingetList | Select-String -SimpleMatch $name -Quiet)
            }
            if ($unmatched) { $unmatched | ForEach-Object { Write-Output "  $_" } }
            else { Write-Output "  Everything installed matches a winget entry." }
        ' 2>&1 | sed 's/\r$//'
    else
        echo "  powershell.exe not found"
    fi
fi

echo ""
echo "Done. Run with --full to also list manually-installed apps winget can't track."
