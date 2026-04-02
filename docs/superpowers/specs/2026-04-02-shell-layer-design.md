# Shell Layer Design

**Date:** 2026-04-02
**Status:** Approved

## Goal

Extend the existing dotfiles repo to version-control and replicate the full terminal setup (shell config, aliases, functions, git config, prompt, tools) across Windows machines running Git Bash.

## Scope

- Windows + Git Bash only (Linux extensibility deferred)
- Source of truth: current machine's `.bashrc`, `.bash_profile`, `.gitconfig`, `starship.toml`
- Machine-specific values (company email, work paths) handled via gitignored local override files

## Repo Structure

```
dotfiles/
├── install.sh                      ← updated to handle shell layer
├── winget-packages.json            ← tool manifest for new machines
│
├── shell/
│   ├── .bashrc                     ← SSH agent, shell options, history, PATH
│   ├── .bash_profile               ← aliases, functions, tools config (portable only)
│   ├── .gitconfig                  ← git config without user identity
│   └── starship.toml               ← prompt config
│
└── claude/                         ← unchanged
    ├── scripts/
    ├── skills/
    └── atlassian/
```

## Local Override Files (gitignored, per machine)

| File | Purpose |
|---|---|
| `~/.bashrc.local` | Machine-specific aliases, work paths, company stuff |
| `~/.gitconfig.local` | `[user]` block with name and email |

## Key Design Decisions

### Company-specific content moved out of `.bash_profile`

The following move from `.bash_profile` into `~/.bashrc.local` on work machines:

- `prj`, `sym` aliases (company repo paths)
- `gk`, `dd`, `sx` aliases (Visual Studio solution shortcuts)
- `code-sym`, `code-chrome` aliases (VS Code workspaces)

### `REPOS_DIR` variable

`ff()` and `fcd()` functions hardcode `/d/repos`. Replace with a variable:

```bash
# In .bash_profile
REPOS_DIR="${REPOS_DIR:-$HOME/repos}"

# In ~/.bashrc.local on this machine
export REPOS_DIR=/d/repos
```

### `.gitconfig` identity

Committed `.gitconfig` includes no `[user]` block. Instead:

```ini
[include]
    path = ~/.gitconfig.local
```

Each machine creates `~/.gitconfig.local`:

```ini
[user]
    name = Constantin Malii
    email = your@email.com
```

### `.bash_profile` local override hook

Added at the very end:

```bash
[ -f ~/.bashrc.local ] && source ~/.bashrc.local
```

## install.sh Changes

- Back up existing `~/.bashrc`, `~/.bash_profile`, `~/.gitconfig` before overwriting
- Copy `shell/` files to their `$HOME` targets
- Copy `shell/starship.toml` to `~/.config/starship.toml`
- Warn (not fail) if `~/.bashrc.local` or `~/.gitconfig.local` are missing

## New Machine Bootstrap Sequence

```bash
# 1. Clone
git clone https://github.com/constantin-malii/dotfiles.git ~/repos/dotfiles
cd ~/repos/dotfiles && bash install.sh

# 2. Create git identity
cat > ~/.gitconfig.local << 'EOF'
[user]
    name = Constantin Malii
    email = your@email.com
EOF

# 3. Create local overrides
touch ~/.bashrc.local   # add machine-specific aliases here

# 4. Install tools
winget import winget-packages.json --ignore-unavailable

# 5. Reload shell
source ~/.bash_profile
```

## Out of Scope

- Linux/WSL support (add later)
- Chezmoi templating
- PowerShell config
- Windows Terminal appearance settings (can be added to `windows/` later)
