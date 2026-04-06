# Shell Layer Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Version-control the full terminal setup (shell config, aliases, functions, git config, prompt, tools) so any new Windows/Git Bash machine can be bootstrapped in one command.

**Architecture:** Copy current machine's shell configs into `shell/` in the repo; surgically remove company-specific values; add a `~/.bashrc.local` / `~/.gitconfig.local` pattern for per-machine overrides; extend `install.sh` to deploy shell files alongside Claude scripts.

**Tech Stack:** Bash, Git Bash (Windows), Starship, winget

---

## File Map

| Action | Path | Responsibility |
|---|---|---|
| Modify | `.gitignore` | Allow `shell/` dotfiles that the current rules would ignore |
| Create | `shell/.bashrc` | SSH agent, shell options, history, PATH — copied from `~/.bashrc` |
| Create | `shell/.bash_profile` | Aliases, functions, tool config — portable only (company stuff removed) |
| Create | `shell/.gitconfig` | Full git config minus `[user]` block — includes `~/.gitconfig.local` |
| Create | `shell/starship.toml` | Prompt config — copied from `~/.config/starship.toml` |
| Create | `winget-packages.json` | Tool manifest exported from current machine |
| Modify | `install.sh` | Add shell layer: backup + copy + missing-override warnings |
| Modify | `README.md` | Update structure docs and new machine bootstrap steps |

---

## Task 1: Fix .gitignore to allow shell config files

**Files:**
- Modify: `.gitignore`

The current `.gitignore` contains `**/.*rc` which would silently ignore `shell/.bashrc`. Fix this before adding any shell files.

- [ ] **Step 1: Verify the problem**

```bash
cd /d/repos/dotfiles
git check-ignore -v shell/.bashrc 2>/dev/null || echo "file doesn't exist yet — rule would match: $(echo 'shell/.bashrc' | git check-ignore --stdin -v 2>/dev/null || echo 'needs testing')"
# Simulate: create temp file and check
touch shell/.bashrc_test
git check-ignore -v shell/.bashrc_test
rm shell/.bashrc_test
```

Expected output: `.gitignore:10:**/.*rc   shell/.bashrc_test` — confirming the rule would match.

- [ ] **Step 2: Add exceptions for shell config files**

In `.gitignore`, find the line `**/.*rc` and add exceptions immediately after it:

```
# Never commit actual credentials or secrets
**/credentials
!**/credentials.template

# Tokens and secrets
**/*token*
**/*secret*
**/*key*
**/*password*
**/.*rc
!shell/.bashrc
!shell/.bash_profile
!shell/.gitconfig
```

- [ ] **Step 3: Verify exceptions work**

```bash
mkdir -p shell
touch shell/.bashrc shell/.bash_profile shell/.gitconfig
git check-ignore -v shell/.bashrc shell/.bash_profile shell/.gitconfig
```

Expected: no output (none of the three are ignored).

```bash
rm shell/.bashrc shell/.bash_profile shell/.gitconfig
```

- [ ] **Step 4: Commit**

```bash
git add .gitignore
git commit -m "fix: allow shell config files through gitignore"
```

---

## Task 2: Export winget package manifest

**Files:**
- Create: `winget-packages.json`

- [ ] **Step 1: Export current machine's packages**

```bash
cd /d/repos/dotfiles
winget export -o winget-packages.json
```

Expected: `winget-packages.json` created with a JSON array of installed packages.

- [ ] **Step 2: Verify the file looks right**

```bash
python -m json.tool winget-packages.json | head -30
```

Expected: valid JSON with `Sources` array containing package entries.

- [ ] **Step 3: Commit**

```bash
git add winget-packages.json
git commit -m "feat: add winget package manifest for new machine setup"
```

---

## Task 3: Add shell/.bashrc

**Files:**
- Create: `shell/.bashrc`

No edits needed — `.bashrc` contains only portable config (SSH agent, shell options, history, env vars, PATH, completion). Copy it verbatim.

- [ ] **Step 1: Copy current .bashrc**

```bash
cp ~/.bashrc /d/repos/dotfiles/shell/.bashrc
```

- [ ] **Step 2: Syntax check**

```bash
bash -n /d/repos/dotfiles/shell/.bashrc && echo "OK: no syntax errors"
```

Expected: `OK: no syntax errors`

- [ ] **Step 3: Verify git sees the file**

```bash
git -C /d/repos/dotfiles status shell/.bashrc
```

Expected: `shell/.bashrc` listed as untracked (not ignored).

- [ ] **Step 4: Commit**

```bash
git add shell/.bashrc
git commit -m "feat: add .bashrc to shell layer"
```

---

## Task 4: Add shell/.bash_profile (portable version)

**Files:**
- Create: `shell/.bash_profile`

This is the most involved task. Copy `.bash_profile` then make three targeted edits:
1. Add `REPOS_DIR` variable and update `ff()` / `fcd()` to use it
2. Remove company-specific aliases
3. Add local override hook at the end

- [ ] **Step 1: Copy current .bash_profile**

```bash
cp ~/.bash_profile /d/repos/dotfiles/shell/.bash_profile
```

- [ ] **Step 2: Add REPOS_DIR variable**

Find the `# Modern CLI Tools` section. Add the `REPOS_DIR` variable **before** it (after the `eval "$(starship init bash)"` line):

```bash
# ============================================================================
# Configurable Paths (override in ~/.bashrc.local)
# ============================================================================

REPOS_DIR="${REPOS_DIR:-$HOME/repos}"
```

- [ ] **Step 3: Update ff() to use REPOS_DIR**

Find the `ff()` function in the `# Modern CLI Tools` section (uses `fd` and `fzf`). Replace the hardcoded path:

Old:
```bash
ff() {
    local file
    file=$(fd ${1:-.} /d/repos | fzf --preview 'bat --color=always {}')
    [ -n "$file" ] && cd "$(dirname "$file")"
}
```

New:
```bash
ff() {
    local file
    file=$(fd ${1:-.} "$REPOS_DIR" | fzf --preview 'bat --color=always {}')
    [ -n "$file" ] && cd "$(dirname "$file")"
}
```

- [ ] **Step 4: Update fcd() to use REPOS_DIR**

Find the `fcd()` function. Replace the hardcoded path:

Old:
```bash
fcd() {
    local dir
    dir=$(fd --type d ${1:-.} /d/repos | fzf --preview 'eza -lah --icons {}')
    [ -n "$dir" ] && cd "$dir"
}
```

New:
```bash
fcd() {
    local dir
    dir=$(fd --type d ${1:-.} "$REPOS_DIR" | fzf --preview 'eza -lah --icons {}')
    [ -n "$dir" ] && cd "$dir"
}
```

- [ ] **Step 5: Remove the Project Navigation section**

Find and delete the entire `# Aliases - Project Navigation` section:

```bash
# ============================================================================
# Aliases - Project Navigation
# ============================================================================

alias prj='cd /c/Users/ConstantinMalii/source/repos'
alias sym='cd /c/Users/ConstantinMalii/source/repos/symend'

# Open solutions in Visual Studio
alias gk='start /c/Users/ConstantinMalii/source/repos/symend/sources/gatekeeper/Gatekeeper.sln'
alias dd='start /c/Users/ConstantinMalii/source/repos/symend/sources/datadesigner/DataDesigner.sln'
alias sx='start /c/Users/ConstantinMalii/source/repos/symend/sources/segmentexplorer/csharp/SegmentExplorer.sln'
```

- [ ] **Step 6: Remove company VS Code aliases**

Find and delete these two lines from `# Aliases - VS Code`:

```bash
alias code-sym='code /c/projects/vs-code-workspaces/symend.code-workspace'
alias code-chrome='code /c/projects/vs-code-workspaces/chrome-extensions.code-workspace'
```

- [ ] **Step 7: Add local override hook at the end**

Append to the very end of `shell/.bash_profile`:

```bash
# ============================================================================
# Machine-specific overrides (not in git — create ~/.bashrc.local per machine)
# ============================================================================
[ -f ~/.bashrc.local ] && source ~/.bashrc.local
```

- [ ] **Step 8: Syntax check**

```bash
bash -n /d/repos/dotfiles/shell/.bash_profile && echo "OK: no syntax errors"
```

Expected: `OK: no syntax errors`

- [ ] **Step 9: Verify no hardcoded company paths remain**

```bash
grep -n "symend\|ConstantinMalii/source\|Gatekeeper\|DataDesigner\|SegmentExplorer" /d/repos/dotfiles/shell/.bash_profile
```

Expected: no output.

- [ ] **Step 10: Commit**

```bash
git add shell/.bash_profile
git commit -m "feat: add portable .bash_profile to shell layer"
```

---

## Task 5: Add shell/.gitconfig (without user identity)

**Files:**
- Create: `shell/.gitconfig`

- [ ] **Step 1: Copy current .gitconfig**

```bash
cp ~/.gitconfig /d/repos/dotfiles/shell/.gitconfig
```

- [ ] **Step 2: Remove the [user] block**

Find and delete these lines from `shell/.gitconfig`:

```ini
[user]
	name = Constantin Malii
	email = constantin@symend.com
```

- [ ] **Step 3: Add [include] at the top**

Add as the very first section (before `[core]`):

```ini
# Machine-specific identity — create ~/.gitconfig.local with [user] block
[include]
	path = ~/.gitconfig.local

```

- [ ] **Step 4: Verify no email remains**

```bash
grep -n "email\|symend" /d/repos/dotfiles/shell/.gitconfig
```

Expected: no output.

- [ ] **Step 5: Verify [include] is present**

```bash
grep -A1 "\[include\]" /d/repos/dotfiles/shell/.gitconfig
```

Expected:
```
[include]
	path = ~/.gitconfig.local
```

- [ ] **Step 6: Commit**

```bash
git add shell/.gitconfig
git commit -m "feat: add .gitconfig to shell layer (identity via .gitconfig.local)"
```

---

## Task 6: Add shell/starship.toml

**Files:**
- Create: `shell/starship.toml`

No edits needed — prompt config has no machine-specific values.

- [ ] **Step 1: Copy current starship config**

```bash
cp ~/.config/starship.toml /d/repos/dotfiles/shell/starship.toml
```

- [ ] **Step 2: Verify it was copied**

```bash
wc -l /d/repos/dotfiles/shell/starship.toml
```

Expected: line count > 50.

- [ ] **Step 3: Commit**

```bash
git add shell/starship.toml
git commit -m "feat: add starship.toml to shell layer"
```

---

## Task 7: Update install.sh

**Files:**
- Modify: `install.sh`

Add a shell section that: backs up existing files, copies shell configs, and warns about missing local overrides.

- [ ] **Step 1: Add shell directory creation to the mkdir line**

Find:
```bash
mkdir -p "$CLAUDE_DIR"/{skills,scripts,atlassian}
```

Replace with:
```bash
mkdir -p "$CLAUDE_DIR"/{skills,scripts,atlassian}
mkdir -p "$HOME/.config"
```

- [ ] **Step 2: Add shell backup logic**

Find the existing backup block:
```bash
if [[ "$MODE" == "update" ]]; then
    echo "Creating backup: $BACKUP_DIR"
    mkdir -p "$BACKUP_DIR"

    # Backup only if files exist
    [[ -d "$CLAUDE_DIR/scripts" ]] && cp -r "$CLAUDE_DIR/scripts" "$BACKUP_DIR/"
    [[ -d "$CLAUDE_DIR/skills" ]] && cp -r "$CLAUDE_DIR/skills" "$BACKUP_DIR/"

    echo "✅ Backup created"
    echo ""
fi
```

Replace with:
```bash
if [[ "$MODE" == "update" ]]; then
    echo "Creating backup: $BACKUP_DIR"
    mkdir -p "$BACKUP_DIR"

    # Backup claude files
    [[ -d "$CLAUDE_DIR/scripts" ]] && cp -r "$CLAUDE_DIR/scripts" "$BACKUP_DIR/"
    [[ -d "$CLAUDE_DIR/skills" ]] && cp -r "$CLAUDE_DIR/skills" "$BACKUP_DIR/"

    # Backup shell configs
    for f in .bashrc .bash_profile .gitconfig; do
        [[ -f "$HOME/$f" ]] && cp "$HOME/$f" "$BACKUP_DIR/$f"
    done
    [[ -f "$HOME/.config/starship.toml" ]] && cp "$HOME/.config/starship.toml" "$BACKUP_DIR/starship.toml"

    echo "✅ Backup created"
    echo ""
fi
```

- [ ] **Step 3: Add shell copy section**

After the `# Copy templates` block and before the final echo block, add:

```bash
# Copy shell configs
if [[ -d "$REPO_DIR/shell" ]]; then
    echo "→ Copying shell configs..."
    [[ -f "$REPO_DIR/shell/.bashrc" ]]       && cp "$REPO_DIR/shell/.bashrc"       "$HOME/.bashrc"
    [[ -f "$REPO_DIR/shell/.bash_profile" ]] && cp "$REPO_DIR/shell/.bash_profile" "$HOME/.bash_profile"
    [[ -f "$REPO_DIR/shell/.gitconfig" ]]    && cp "$REPO_DIR/shell/.gitconfig"    "$HOME/.gitconfig"
    [[ -f "$REPO_DIR/shell/starship.toml" ]] && cp "$REPO_DIR/shell/starship.toml" "$HOME/.config/starship.toml"
fi

# Warn about missing local overrides (never fail — they're optional)
echo ""
echo "→ Checking local overrides..."
if [[ ! -f "$HOME/.bashrc.local" ]]; then
    echo "⚠️  ~/.bashrc.local not found — create it for machine-specific aliases/paths"
fi
if [[ ! -f "$HOME/.gitconfig.local" ]]; then
    echo "⚠️  ~/.gitconfig.local not found — git commits will have no author identity"
    echo "   Create it with:"
    echo "   printf '[user]\n\tname = Your Name\n\temail = you@example.com\n' > ~/.gitconfig.local"
fi
```

- [ ] **Step 4: Syntax check install.sh**

```bash
bash -n /d/repos/dotfiles/install.sh && echo "OK: no syntax errors"
```

Expected: `OK: no syntax errors`

- [ ] **Step 5: Dry-run verify (list what would be copied)**

```bash
bash -c '
REPO_DIR=/d/repos/dotfiles
for f in shell/.bashrc shell/.bash_profile shell/.gitconfig shell/starship.toml; do
    [[ -f "$REPO_DIR/$f" ]] && echo "FOUND: $f" || echo "MISSING: $f"
done
'
```

Expected: all four lines show `FOUND`.

- [ ] **Step 6: Commit**

```bash
git add install.sh
git commit -m "feat: extend install.sh to deploy shell layer"
```

---

## Task 8: Update README.md

**Files:**
- Modify: `README.md`

Update the repo structure section and add new machine bootstrap steps.

- [ ] **Step 1: Update the Structure section**

Find the existing `## Structure` code block and replace it with:

```markdown
## Structure

\`\`\`
dotfiles/
├── install.sh                      # Install/update script
├── winget-packages.json            # Tool manifest for new machines
├── README.md                       # This file
│
├── shell/
│   ├── .bashrc                     # SSH agent, shell opts, history, PATH
│   ├── .bash_profile               # Aliases, functions, tool config (portable)
│   ├── .gitconfig                  # Git config (identity via ~/.gitconfig.local)
│   └── starship.toml               # Prompt config
│
└── claude/
    ├── scripts/                    # Atlassian scripts
    ├── skills/                     # Claude Code skills
    └── atlassian/                  # Credential templates
\`\`\`
```

- [ ] **Step 2: Replace the Installation section**

Find `### First Time Setup` and replace the entire installation section with:

```markdown
### First Time Setup

\`\`\`bash
# 1. Clone
git clone https://github.com/constantin-malii/dotfiles.git ~/repos/dotfiles
cd ~/repos/dotfiles && bash install.sh

# 2. Set git identity (required — never committed to git)
printf '[user]\n\tname = Your Name\n\temail = you@example.com\n' > ~/.gitconfig.local

# 3. Create local overrides file (add machine-specific aliases here)
touch ~/.bashrc.local

# 4. Install tools
winget import winget-packages.json --ignore-unavailable

# 5. Setup Atlassian credentials
bash ~/.claude/scripts/setup-credentials-interactive.sh

# 6. Reload shell
source ~/.bash_profile
\`\`\`

### Machine-specific config

Two files are **never committed** — create them per machine:

**`~/.gitconfig.local`** — your git identity:
\`\`\`ini
[user]
    name = Your Name
    email = you@example.com
\`\`\`

**`~/.bashrc.local`** — machine-specific aliases and paths:
\`\`\`bash
# Example work machine overrides
export REPOS_DIR=/c/Users/YourName/source/repos
alias prj='cd $REPOS_DIR'
\`\`\`
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: update README for shell layer and new machine bootstrap"
```

---

## Self-Review

**Spec coverage check:**
- [x] `shell/.bashrc` — Task 3
- [x] `shell/.bash_profile` portable (company aliases removed) — Task 4
- [x] `REPOS_DIR` variable replacing `/d/repos` — Task 4
- [x] `~/.bashrc.local` hook at end of `.bash_profile` — Task 4
- [x] `shell/.gitconfig` without `[user]`, with `[include]` — Task 5
- [x] `shell/starship.toml` — Task 6
- [x] `winget-packages.json` — Task 2
- [x] `install.sh` backup + copy + warnings — Task 7
- [x] `.gitignore` fix for `**/.*rc` rule — Task 1
- [x] README new machine bootstrap — Task 8

**No placeholders:** All steps contain exact commands, file content, or specific edit instructions.

**Consistency check:** `REPOS_DIR` variable defined in Task 4 Step 2 and used in Steps 3 and 4. `~/.gitconfig.local` format consistent between Task 5, Task 7 (warning message), and Task 8 (README).
