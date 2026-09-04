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

## Rollback safety

Before touching anything, `updates-apply` tries to create a **System Restore point** (requires an elevated shell). If it succeeds, one command undoes the whole batch:

```powershell
rstrui.exe                              # interactive restore UI
# or
Get-ComputerRestorePoint                # find the sequence number
Restore-Computer -RestorePoint <seq>    # non-interactive, will reboot
```

Caveats:
- Requires elevation. Running `updates-apply` from a non-elevated shell skips the restore point and proceeds anyway (with a warning) — re-run elevated if you want the safety net.
- Windows throttles restore-point creation to once per 24 hours by default. A second run the same day may silently reuse/skip — check `Get-ComputerRestorePoint` if unsure one was actually made.
- System Restore mainly covers system files, registry, and installed programs — it does not reliably undo Windows Update installations. Use the per-source rollback below for anything restore doesn't catch.

**Per-source manual rollback**, if restore isn't available or doesn't cover it:

| Source | Rollback |
|---|---|
| Choco | `choco install <pkg> --version=<old-version>` (downgrade, if the old version is still in the source cache) |
| Winget | No built-in downgrade — reinstall the specific older version manually: `winget install <id> --version <old-version>` (only works if that version is still published) |
| Windows Update | `Get-WUHistory` to find the KB, then `wusa /uninstall /kb:<number>` or `Remove-WindowsUpdate -KBArticleID <number>` (from `PSWindowsUpdate`) |

## Scope / limitations

- **`updates` / `updates-full` never install anything** — report only. Use `updates-apply` to actually apply winget/choco updates, or update by hand (`winget upgrade <id>`, `choco upgrade <id>`, Windows Update, or the app's own updater).
- **Doesn't cover** browser extensions, VS Code extensions, npm/pip globals, or anything not tracked by winget/choco/Windows Update — out of scope by design; too much surface area to track reliably.
- Manually-installed apps that winget *does* recognize (matched by name/publisher heuristics) are already covered by the winget section — `--full`'s extra list is only for apps winget has no idea about.
