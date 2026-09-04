# Update Checker

Checks OS updates and app updates from one command instead of checking Windows Update and each app individually.

---

## Usage

```bash
updates          # check winget, choco, Windows Update, and Claude plugins
updates-full     # same, plus list installed apps winget doesn't recognize
```

Script: `claude/scripts/check-updates.sh`, deployed to `~/.claude/scripts/check-updates.sh` by `bash install.sh --claude`.

Run from a normal Git-Bash or PowerShell terminal — not a sandboxed/restricted shell, since winget needs write access to `C:\WINDOWS\WinGet`.

For the **Windows OS updates** section, run from an **elevated** terminal (Run as Administrator). In a non-elevated shell it prints `Skipped: requires an elevated (Run as Administrator) shell.` instead of silently reporting nothing.

## What it checks

| Section | Source | Notes |
|---|---|---|
| Winget apps | `winget upgrade --include-unknown` | Covers most apps in `winget-packages.json`, plus manually-installed apps winget can still identify by catalog match |
| Chocolatey apps | `choco outdated` | Covers navi, curlie, ctop, and any other choco-installed tool |
| Windows OS updates | `PSWindowsUpdate` module (`Get-WindowsUpdate`) | Requires elevation; module installs once, see below |
| Claude Code plugins | `claude plugin marketplace update` + `claude plugin list --json --available` (diffed with `jq`) | Flags installed plugins with a newer version available |
| Manually-installed apps (`--full` only) | Registry uninstall keys vs. `winget list` | Apps winget has no catalog entry for at all — nothing else here checks these; review and update by hand |

## One-time setup: Windows Update module

The OS-updates section needs the `PSWindowsUpdate` PowerShell module. Install once, per machine:

```powershell
Install-PackageProvider -Name NuGet -MinimumVersion 2.8.5.201 -Force -Scope CurrentUser
Install-Module PSWindowsUpdate -Scope CurrentUser -Force
```

Without it, the script prints the install command instead of failing.

## Scope / limitations

- **Doesn't auto-install anything.** It's a checker, not an updater — it only lists what's outdated. Apply updates yourself (`winget upgrade <id>`, `choco upgrade <id>`, Windows Update, or the app's own updater).
- **Doesn't cover** browser extensions, VS Code extensions, npm/pip globals, or anything not tracked by winget/choco/Windows Update — out of scope by design; too much surface area to track reliably.
- Manually-installed apps that winget *does* recognize (matched by name/publisher heuristics) are already covered by the winget section — `--full`'s extra list is only for apps winget has no idea about.
