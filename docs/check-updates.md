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
updates-apply                 # non-elevated: prompts before winget upgrade --all
updates-apply --yes           # same, no prompts
updates-apply --os            # elevated only: prompts for choco upgrade all, and (with --os) Windows Update
updates-apply --defer-git     # also queues a background watcher to upgrade Git once you close everything
updates-apply --defer-claude  # also queues a background watcher to upgrade the Claude desktop app once it's closed
```

**Run it twice, in two different shells — this is intentional, not a bug:**

- **Non-elevated** shell → does winget only. Skips choco and Windows Update.
- **Elevated** (Run as Administrator) shell → does choco, and Windows Update if `--os` is passed. Skips winget.

Why: winget refuses to upgrade a user-scope package (glow, tealdeer, etc.) when run elevated — `"The package installed for user scope cannot be uninstalled when running with administrator privileges."` Choco, on the other hand, needs elevation to do anything at all (non-elevated it prints a warning, times out on a prompt, and upgrades nothing). Windows Update also requires elevation. There's no single elevation state that satisfies all three, so the script detects which one it's in and runs only the matching subset, telling you to re-run the other way for the rest.

**Known gotcha — Git can never self-upgrade while anything is using Git Bash.** `winget upgrade Git.Git` (and `git update-git-for-windows`) both fail whenever any bash/ssh-agent process is running — the Git-for-Windows installer refuses to proceed and lists the blocking PIDs.

This is broader than "close your Git Bash windows": **Claude Code itself keeps Git Bash processes alive** in the background (its own tool shell, plus a statusline script that shells out on every prompt) for as long as the CLI is open — even if you don't have a visible Git Bash terminal. `git update-git-for-windows` silently fails under this condition too (it tries to kill the blocking process and can't, and just abandons the update — check `%TEMP%\gfw-install-*.exe`: 0-byte files there are failed attempts).

To upgrade Git, either:

**A. Manually**, once you're closing everything anyway:
1. Close **every** terminal window, including any window running Claude Code.
2. Open a fresh PowerShell or cmd window with nothing else open.
3. Run:
   ```powershell
   winget upgrade Git.Git
   ```

**B. Deferred**, via `updates-apply --defer-git`:

```bash
updates-apply --defer-git
```

This queues a detached background watcher (`claude/scripts/winget-upgrade-watcher.ps1 -Target bash-claude`) that polls every 15 seconds for any running `bash` or `claude` process. Once none remain anywhere on the machine — i.e. once you've closed every terminal, including this Claude Code session — it runs `winget upgrade Git.Git` on its own and logs the result. Gives up after 3 hours if bash/claude never fully exit.

Check on it any time:
```bash
cat ~/.claude/logs/git-upgrade-watcher.log
```

The watcher is a standalone process (`Start-Process`, not a child of the calling shell), so it survives this session, this terminal, and Claude Code all closing.

### Claude desktop app

The Claude desktop app has the same self-lock problem as Git: winget can't replace its files while it's running. Unlike Git, this only needs the **desktop app** closed — not Claude Code — since they're separate products that happen to share the `claude.exe` process name (the watcher tells them apart by install path: the desktop app lives under `WindowsApps\Claude_*`, Claude Code's CLI binary lives under `~/.local/bin`).

```bash
updates-apply --defer-claude
```

Queues the same watcher (`-Target claude-desktop`), logging to `~/.claude/logs/claude-desktop-upgrade-watcher.log`. Note the desktop app usually self-updates on its own in the background already — winget's version often just lags until you relaunch it — so this is mainly useful when winget shows a genuinely newer version and the app won't take it.

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
