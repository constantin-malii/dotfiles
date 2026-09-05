# Waits until the processes blocking a winget upgrade have exited, then runs
# the upgrade. Launched detached (Start-Process) by apply-updates.sh so it
# survives the calling shell closing.
#
# -Target 'bash-claude' waits for any bash.exe or claude.exe process anywhere
#   (used for Git, which is blocked by any open Git Bash / Claude Code session).
# -Target 'claude-desktop' waits only for claude.exe processes running from
#   the desktop app's WindowsApps install path — NOT the Claude Code CLI,
#   which is also named claude.exe but lives under a different path. This
#   means closing the desktop app (not Claude Code) is enough.
param(
    [Parameter(Mandatory = $true)]
    [string]$LogPath,

    [Parameter(Mandatory = $true)]
    [string]$WingetId,

    [Parameter(Mandatory = $true)]
    [ValidateSet('bash-claude', 'claude-desktop')]
    [string]$Target
)

function Log($msg) {
    "[$(Get-Date -Format s)] $msg" | Out-File -FilePath $LogPath -Append -Encoding utf8
}

function Get-BlockingProcesses {
    if ($Target -eq 'bash-claude') {
        Get-Process -Name 'bash', 'claude' -ErrorAction SilentlyContinue
    } else {
        Get-Process -Name 'claude' -ErrorAction SilentlyContinue | Where-Object {
            try { $_.Path -like '*\WindowsApps\Claude_*' } catch { $false }
        }
    }
}

Log "Watcher started (PID $PID) for $WingetId, target=$Target, waiting for blocking processes to exit..."

$maxWaitMinutes = 180
$deadline = (Get-Date).AddMinutes($maxWaitMinutes)

while (Get-BlockingProcesses) {
    if ((Get-Date) -gt $deadline) {
        Log "Timed out after $maxWaitMinutes minutes waiting for blocking processes to exit. Giving up."
        exit 1
    }
    Start-Sleep -Seconds 15
}

Log "No blocking processes remain. Upgrading $WingetId..."
try {
    $result = winget upgrade $WingetId --accept-source-agreements --accept-package-agreements 2>&1
    $result | Out-File -FilePath $LogPath -Append -Encoding utf8
    Log "Done."
} catch {
    Log "Upgrade failed: $($_.Exception.Message)"
}
