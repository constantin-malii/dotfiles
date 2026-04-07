# Claude Code Instructions

## Commits and PRs

- Do NOT mention Claude, Claude Code, or AI in commit messages or PR descriptions
- No `Co-Authored-By: Claude` lines in commits
- Write commit messages as if authored by a human developer

---

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

## Tool Configs

Tool-specific configs live in `config/` and are deployed by `install.sh`:

| File | Deployed to |
|------|-------------|
| `config/lazygit.yml` | `~/.config/lazygit/config.yml` |
| `config/lazydocker.yml` | `~/.config/lazydocker/config.yml` |

When changing lazygit or lazydocker settings, edit the files in `config/` and run `bash install.sh`.

To sync settings changed in the UI back to the repo:
```bash
cp ~/.config/lazygit/config.yml ~/repos/dotfiles/config/lazygit.yml
cp ~/.config/lazydocker/config.yml ~/repos/dotfiles/config/lazydocker.yml
```

## Tools (winget)

When a new tool is installed on this machine and should be available on all machines:
1. Run: `winget export -o winget-packages.json`
2. Commit the updated `winget-packages.json`

---

## Agent Task Guide

Use this section when asked to perform common maintenance tasks in this repo.

### Verify install is complete

```bash
bash verify.sh
```

Checks: local override files, shell files, SSH connections, Atlassian credentials, Claude scripts/skills, tool configs (lazygit, lazydocker), Windows Terminal, CLI tools. Returns exit code 0 on success, 1 if anything is missing.

### Bootstrap a new machine

Follow this exact sequence — do not skip steps:

```bash
# 1. Generate SSH keys (if ~/.ssh/id_work and ~/.ssh/id_personal don't exist)
ssh-keygen -t ed25519 -C "work@company.com" -f ~/.ssh/id_work -N ""
ssh-keygen -t ed25519 -C "personal@email.com" -f ~/.ssh/id_personal -N ""

# 2. Create ~/.ssh/config (if it doesn't exist)
cat > ~/.ssh/config << 'EOF'
Host github-work
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_work

Host github-personal
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_personal
EOF

# 3. Show public keys for the user to add to GitHub
cat ~/.ssh/id_work.pub
cat ~/.ssh/id_personal.pub
# STOP — tell the user to add these to the correct GitHub accounts before continuing

# 4. Test SSH (after user confirms keys are added)
ssh -T git@github-work      # must say: Hi constantin-malii!
ssh -T git@github-personal  # must say: Hi constantinmalii!

# 5. Clone
git clone git@github-work:constantin-malii/dotfiles.git ~/repos/dotfiles
cd ~/repos/dotfiles && bash install.sh

# 6. Create local identity
printf '[user]\n\tname = Your Name\n\temail = you@email.com\n' > ~/.gitconfig.local

# 7. Create local overrides
touch ~/.bashrc.local
# Ask the user what REPOS_DIR should be and what work aliases to add

# 8. Install CLI tools
winget install Starship.Starship sharkdp.bat eza-community.eza junegunn.fzf \
  BurntSushi.ripgrep.MSVC sharkdp.fd ajeetdsouza.zoxide atuinsh.atuin \
  JesseDuffield.lazygit charmbracelet.glow dandavison.delta jqlang.jq \
  MikeFarah.yq GitHub.cli --accept-package-agreements --accept-source-agreements

# 9. Install Nerd Font (required for starship icons)
winget install DEVCOM.JetBrainsMonoNerdFont --accept-package-agreements --accept-source-agreements

# 10. Set up Atlassian credentials
bash ~/.claude/scripts/setup-credentials-interactive.sh

# 11. Verify
bash verify.sh
```

### Add a new shell alias or function

1. Edit `shell/.bash_profile` in the repo (not `~/.bash_profile`)
2. Place in the appropriate section (aliases by category, functions near similar functions)
3. Run `bash install.sh` to deploy
4. Run `source ~/.bash_profile` to activate in current session
5. Commit

### Add a new CLI tool

1. Install the tool: `winget install Publisher.ToolName`
2. Update the manifest: `winget export -o winget-packages.json`
3. Add any aliases or config to `shell/.bash_profile` if needed
4. Run `bash install.sh` if shell changes were made
5. Commit both `winget-packages.json` and any shell changes

### Add a new Claude script

1. Create the script in `claude/scripts/`
2. If it belongs to a skill, add it to the `SKILL_SCRIPTS` mapping in `install.sh`
3. Run `bash install.sh --only <skill>` to deploy
4. Test: `bash ~/.claude/scripts/<script-name>.sh`
5. Commit

### Add a new agent

Agents are reusable subagent definitions available in every project.

1. Create `claude/agents/<name>.md` in the repo
2. Run `bash install.sh` to deploy to `~/.claude/agents/`
3. Commit

Format: standard Claude Code agent markdown with `name`, `description`, and instructions.

### Add a new command

Commands are custom slash commands available in every project.

1. Create `claude/commands/<name>.md` in the repo
2. Run `bash install.sh` to deploy to `~/.claude/commands/`
3. Commit

Format: standard Claude Code command markdown.

### Update Atlassian credentials

```bash
bash ~/.claude/scripts/setup-credentials-interactive.sh
```

Credentials are stored in `~/.atlassian/credentials` (gitignored — never committed).

### Troubleshoot SSH wrong account

```bash
ssh -T git@github-work      # check which account is returned
ssh -T git@github-personal
cat ~/.ssh/config            # verify IdentityFile mapping
ssh-add -l                  # check if agent is overriding config
```

If SSH agent is overriding config, force the key:
```bash
ssh -i ~/.ssh/id_work -T git@github.com
```

### Roll back a bad install

```bash
ls ~/.claude/.backup-*      # find latest backup timestamp
cp -r ~/.claude/.backup-TIMESTAMP/* ~/.claude/
# Also restore shell files if they were changed:
cp ~/.claude/.backup-TIMESTAMP/.bashrc ~/.bashrc
cp ~/.claude/.backup-TIMESTAMP/.bash_profile ~/.bash_profile
cp ~/.claude/.backup-TIMESTAMP/.gitconfig ~/.gitconfig
source ~/.bash_profile
```
