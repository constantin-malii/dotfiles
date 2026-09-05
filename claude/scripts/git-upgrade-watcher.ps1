# Waits until no bash/claude process is running anywhere on the machine,
# then upgrades Git for Windows via winget. Launched detached by
# apply-updates.sh --defer-git so it survives the calling shell (and Claude
# Code) closing.
param(
    [Parameter(Mandatory = $true)]
    [string]$LogPath
)

function Log($msg) {
    "[$(Get-Date -Format s)] $msg" | Out-File -FilePath $LogPath -Append -Encoding utf8
}

Log "Watcher started (PID $PID), waiting for bash/claude processes to exit..."

$maxWaitMinutes = 180
$deadline = (Get-Date).AddMinutes($maxWaitMinutes)

while (Get-Process -Name 'bash', 'claude' -ErrorAction SilentlyContinue) {
    if ((Get-Date) -gt $deadline) {
        Log "Timed out after $maxWaitMinutes minutes waiting for bash/claude to exit. Giving up."
        exit 1
    }
    Start-Sleep -Seconds 15
}

Log "All bash/claude processes exited. Upgrading Git..."
try {
    $result = winget upgrade Git.Git --accept-source-agreements --accept-package-agreements 2>&1
    $result | Out-File -FilePath $LogPath -Append -Encoding utf8
    Log "Done."
} catch {
    Log "Upgrade failed: $($_.Exception.Message)"
}
