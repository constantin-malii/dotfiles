# Update Checker

Checks OS updates and app updates from one command instead of checking Windows Update and each app individually.

---

## Usage

```bash
updates          # check winget, choco, Windows Update, and Claude plugins
updates-full     # same, plus list installed apps winget doesn't recognize
updates-apply    # apply outdated winget/choco packages, with a confirm prompt per category
```

Scripts: `claude/scripts/check-updates.sh` (report only) and `claude/scripts/apply-updates.sh` (applies updates), deployed to `~/.claude/scripts/` by `bash install.sh --claude`.

`updates` and `updates-full` never install anything — they only list what's outdated. `updates-apply` is the one that changes your system, and it asks for confirmation before touching winget or choco. Pass `--yes` to skip prompts, `--os` to also install pending Windows Updates (still prompted unless combined with `--yes`; requires an elevated shell).

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

## Applying updates

```bash
updates-apply            # prompts before winget upgrade --all and choco upgrade all
updates-apply --yes      # same, no prompts
updates-apply --os       # also offers to install pending Windows Updates (elevated shell required)
```

Windows Updates are opt-in via `--os` and always require an elevated terminal — OS-level updates can trigger a reboot, so they're excluded by default even with `--yes` unless `--os` is also passed.

## Scope / limitations

- **`updates` / `updates-full` never install anything** — report only. Use `updates-apply` to actually apply winget/choco updates, or update by hand (`winget upgrade <id>`, `choco upgrade <id>`, Windows Update, or the app's own updater).
- **Doesn't cover** browser extensions, VS Code extensions, npm/pip globals, or anything not tracked by winget/choco/Windows Update — out of scope by design; too much surface area to track reliably.
- Manually-installed apps that winget *does* recognize (matched by name/publisher heuristics) are already covered by the winget section — `--full`'s extra list is only for apps winget has no idea about.
