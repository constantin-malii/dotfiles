# Claude Code Instructions

## Commits and PRs

- Do NOT mention Claude, Claude Code, or AI in commit messages or PR descriptions
- No `Co-Authored-By: Claude` lines in commits
- Write commit messages as if authored by a human developer

## Shell Config

**Always edit `shell/` — never `~/`**
- `shell/.bashrc`, `shell/.bash_profile`, `shell/.gitconfig`, `shell/starship.toml` are the source of truth
- `~/.bash_profile` etc. are deployed copies — they get overwritten by `bash install.sh`
- If asked to add/change an alias or function, edit the file in `shell/`

**Local override pattern**
- `~/.bashrc.local` and `~/.gitconfig.local` are gitignored and per-machine — never committed
- Company-specific aliases, work paths, and personal git identity belong there, not in `shell/`
- Do not move content from `~/.bashrc.local` into the committed shell files

**Intentionally removed from `shell/.bash_profile`**
The following were in the original `~/.bash_profile` but removed because they are work-machine-specific.
They live in `~/.bashrc.local` on work machines — do not add them back to `shell/`:

```bash
# Work repo navigation
alias prj='cd /c/Users/ConstantinMalii/source/repos'
alias sym='cd /c/Users/ConstantinMalii/source/repos/symend'

# Visual Studio solutions (Symend)
alias gk='start .../Gatekeeper.sln'
alias dd='start .../DataDesigner.sln'
alias sx='start .../SegmentExplorer.sln'

# VS Code workspaces (Symend)
alias code-sym='code .../symend.code-workspace'
alias code-chrome='code .../chrome-extensions.code-workspace'
```

## Tools (winget)

When a new tool is installed on this machine and should be available on all machines:
1. Run: `winget export -o winget-packages.json`
2. Commit the updated `winget-packages.json`
