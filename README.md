# Personal Dotfiles

A portable terminal setup for Windows/Git Bash — shell config, git config, prompt, CLI tools, and Claude Code skills for Jira, Confluence, and Azure DevOps. Clone once, run one script, and any machine is fully configured.

---

## What You Get

| Layer | What it sets up |
|---|---|
| **Shell** | Aliases, functions, prompt (Starship), SSH agent, history |
| **Git** | Aliases, delta diffs, rerere, merge tools |
| **Tools** | bat, eza, fzf, ripgrep, lazygit, atuin, zoxide, broot, duf, procs, dust, and more |
| **Claude Skills** | `/jira`, `/confluence`, `/azure-devops`, `/skillify`, `/tech-debt`, `/ddup`, `/verify-template` |
| **Atlassian Scripts** | Jira + Confluence REST API wrappers usable from Claude or terminal |

---

## Prerequisites

- Windows with Git Bash
- [winget](https://learn.microsoft.com/en-us/windows/package-manager/winget/) (built into Windows 11)
- Python 3 (for Confluence large upload and Jira template scripts)
- Claude Code CLI (for skills)

---

## First-Time Setup on a New Machine

### 1. Configure SSH

This repo uses SSH with named host aliases to keep accounts separate. Configure whichever hosts you need:

**Generate keys:**
```bash
# GitHub (ed25519)
ssh-keygen -t ed25519 -C "personal@email.com" -f ~/.ssh/id_personal
ssh-keygen -t ed25519 -C "work@company.com" -f ~/.ssh/id_work

# Azure DevOps (requires RSA — ed25519 not supported)
ssh-keygen -t rsa -b 4096 -m PEM -C "work@company.com" -f ~/.ssh/id_work_rsa
```

**Create `~/.ssh/config`** (include only the hosts you need):
```
# Personal GitHub
Host github-personal
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_personal

# Work GitHub
Host github-work
    HostName github.com
    User git
    IdentityFile ~/.ssh/id_work

# Azure DevOps (requires RSA key)
Host ssh.dev.azure.com
    HostName ssh.dev.azure.com
    User git
    IdentityFile ~/.ssh/id_work_rsa
```

**Add public keys to the relevant services:**
- GitHub → Settings → SSH and GPG keys → New SSH key
- Azure DevOps → User Settings → SSH Public Keys → Add

**Test connections:**
```bash
ssh -T git@github-personal  # Should say: Hi <username>!
ssh -T git@github-work      # Should say: Hi <username>!
ssh -T git@ssh.dev.azure.com # Should say: shell request failed (= success)
```

### 2. Clone and install

```bash
git clone git@github-work:constantin-malii/dotfiles.git ~/repos/dotfiles
cd ~/repos/dotfiles
bash install.sh
```

### 3. Set git identity (per machine — never committed)

```bash
printf '[user]\n\tname = Your Name\n\temail = you@company.com\n' > ~/.gitconfig.local
```

### 4. Set machine-specific shell config (per machine — never committed)

```bash
cat > ~/.bashrc.local << 'EOF'
# Repos root (used by ff() and fcd() functions)
export REPOS_DIR=/d/repos

# Work navigation aliases
alias prj='cd /c/Users/YourName/source/repos'
alias sym='cd /c/Users/YourName/source/repos/company'
EOF
```

### 5. Install tools

```bash
winget import winget-packages.json --ignore-unavailable
```

This installs CLI tools (starship, bat, fzf, ripgrep, etc.), the Nerd Font for starship icons, and Windows Terminal. See `winget-packages.json` for the full list.

**Tools not on winget** (require chocolatey):
```bash
choco install navi curlie ctop -y
```
- **navi** — interactive cheatsheets (`Ctrl+G`)
- **curlie** — HTTPie-style curl (`get`, `post`, `http` aliases)
- **ctop** — container monitoring

### 6. Set up Atlassian credentials

```bash
bash ~/.claude/scripts/setup-credentials-interactive.sh
# Prompts for: email, API token, Jira URL, Confluence URL
```

### 7. Reload shell

```bash
source ~/.bash_profile
```

---

## Updating an Existing Machine

```bash
cd ~/repos/dotfiles
git pull
bash install.sh  # backs up existing files before overwriting
```

Backups are saved to `~/.claude/.backup-TIMESTAMP/`. To roll back:
```bash
ls ~/.claude/.backup-*         # find the backup
cp -r ~/.claude/.backup-TIMESTAMP/* ~/.claude/
cp ~/.claude/.backup-TIMESTAMP/.bashrc ~/.bashrc
cp ~/.claude/.backup-TIMESTAMP/.bash_profile ~/.bash_profile
```

---

## Selective Install (single skill)

Install selectively:

```bash
bash install.sh --claude          # only Claude Code files (skills, commands, agents)
bash install.sh --shell           # only shell configs (.bash_profile, .gitconfig, starship)
bash install.sh --config          # only tool configs (lazygit, lazydocker, terminal)
bash install.sh --list            # see available skills
bash install.sh --only jira       # only the jira skill + its scripts
bash install.sh --only confluence
bash install.sh --only azure-devops
```

---

## Shell Layer

### Prompt

[Starship](https://starship.rs/) — shows username, directory, git branch/status, battery, memory, language versions, command duration.

Config: `shell/starship.toml` → installed to `~/.config/starship.toml`

### Key Aliases

**Navigation:**
```bash
z <dir>        # smart cd (zoxide — learns your frequent dirs)
br             # interactive directory browser (broot)
fcd [pattern]  # fuzzy cd into any dir under $REPOS_DIR
ff [pattern]   # fuzzy find file, cd to its directory
```

**File listing:**
```bash
ls             # eza with icons
ll             # eza long format with git status
lt             # eza tree (2 levels)
tree2/tree3    # eza tree at depth 2 or 3
treeg          # eza tree respecting .gitignore
```

**File viewing:**
```bash
cat <file>     # bat with syntax highlighting
catn <file>    # bat with line numbers
md <file>      # glow — render markdown in terminal
readme         # glow README.md in current dir
```

**Search:**
```bash
rg <pattern>   # ripgrep (respects .gitignore)
rgi <pattern>  # ripgrep case-insensitive
rgf <name>     # find files by name via ripgrep
fif <pattern>  # fuzzy search file contents with preview
```

**Git:**
```bash
gs             # git status
gd / gdc       # git diff / diff --cached
gf / gfp       # git fetch / fetch + pull
glog           # git log graph all branches
gls            # git log oneline last 20
gundo          # git reset --soft HEAD~1
gc <branch>    # checkout branch
gcb <branch>   # checkout new branch
gcm "msg"      # git add . && commit
gcp "msg"      # git add . && commit && push
gtrack         # show all branch tracking info
gclean         # delete merged local branches
fgb            # fuzzy interactive branch checkout
lg             # lazygit TUI
```

**Docker:**
```bash
dps / dpsa     # docker ps (running / all)
dcup / dcdown  # docker compose up -d / down
dlogs <name>   # docker logs -f --tail 100
dsh <name>     # shell into container
dins <name>    # inspect container as JSON
dstats         # container resource usage
dfullclean     # full docker prune (containers/images/volumes/networks)
lzd            # lazydocker TUI
```

**Utilities:**
```bash
mkcd <dir>     # mkdir + cd in one
extract <file> # extract any archive format
weather [city] # weather in terminal
serve [port]   # quick HTTP server (default: 8000)
dsize [dir]    # directory sizes sorted
loc            # count lines of code
mdprint <file> # convert markdown to HTML and open in browser
```

**FZF key bindings:**
```
Ctrl+R         # fuzzy search command history (also uses atuin)
Ctrl+T         # fuzzy find file, paste path
Alt+C          # fuzzy cd
Ctrl+G         # navi interactive cheatsheets
```

**JSON/YAML:**
```bash
jqp / jqk      # jq pretty print / show keys
jqf [file]     # jq pretty print with color pager
j2y / y2j      # convert JSON↔YAML
get <url>      # HTTP GET with pretty output (curlie)
post <url>     # HTTP POST with JSON
```

### Shell Features

- **atuin** — shell history synced across machines, searchable with context
- **direnv** — auto-load `.envrc` per directory (activate venvs, set env vars)
- **zoxide** — smart `cd` that learns your most-used directories
- **Auto ls after cd** — every `cd` shows directory contents automatically

---

## Git Config

`shell/.gitconfig` → installed to `~/.gitconfig`

Notable settings:
- **Delta** — syntax-highlighted side-by-side diffs as default pager
- **rerere** — remembers conflict resolutions
- **histogram diff** algorithm
- **Auto prune** on fetch
- **Auto setup remote** on push

Key git aliases (in addition to shell aliases above):
```bash
git lg          # graph log with colors
git lga         # graph log all branches
git wip         # quick "WIP: timestamp" commit
git unwip       # undo last WIP commit
git cleanup     # delete merged branches
git find "msg"  # search commits by message
git stash-show  # show stash diff
git undo        # soft reset last commit
git amend       # amend without editing message
```

Identity is loaded from `~/.gitconfig.local` (never committed):
```ini
[user]
    name = Your Name
    email = you@company.com
```

---

## Windows Terminal

`windows/terminal-settings.json` → installed to `%LOCALAPPDATA%\Packages\Microsoft.WindowsTerminal_8wekyb3d8bbwe\LocalState\settings.json`

**What's configured:**

| Setting | Value |
|---|---|
| Theme | Dracula (full color scheme embedded) |
| Font | JetBrainsMono Nerd Font, size 11 |
| Default profile | Git Bash |
| Opacity | 90–95% with acrylic blur |
| Initial size | 120×30, launches maximized |
| Cursor | Bar style |

**Custom keybindings:**

| Key | Action |
|---|---|
| `Ctrl+Shift+T` | New tab |
| `Ctrl+Tab` / `Ctrl+Shift+Tab` | Next/prev tab |
| `Alt+Shift++` | Split pane right |
| `Alt+Shift+-` | Split pane down |
| `Alt+Shift+D` | Auto split |
| `Alt+←↑→↓` | Move focus between panes |
| `Ctrl+Shift+W` | Close pane |
| `Ctrl+,` | Open settings |

**Updating terminal settings:**

Make changes in Windows Terminal UI, then sync back to the repo:
```bash
cp "$LOCALAPPDATA/Packages/Microsoft.WindowsTerminal_8wekyb3d8bbwe/LocalState/settings.json" \
   ~/repos/dotfiles/windows/terminal-settings.json
cd ~/repos/dotfiles && git add windows/terminal-settings.json
git commit -m "chore: update Windows Terminal settings"
git push
```

---

## Claude Code Skills

Skills are slash commands in Claude Code that give Claude context and tools for specific workflows.

### /jira — Jira Issue Management

Full CRUD for Jira issues with git workflow integration.

```bash
/jira mine                                    # your open issues
/jira get PROJ-123                            # issue details
/jira search "project=PL AND status=Open"     # JQL search
/jira create PL "Fix login bug" "Description" Bug
/jira update PROJ-123 summary "New title"
/jira update PROJ-123 description "New desc"
/jira transition PROJ-123 "In Progress"       # change status
/jira transition PROJ-123                     # list available transitions
/jira assign PROJ-123 me
/jira assign PROJ-123 user@company.com
/jira comment PROJ-123 "Comment text"
/jira comments PROJ-123                       # list comments
/jira labels PROJ-123 add "bug,urgent"
/jira labels PROJ-123 remove "urgent"
/jira link PROJ-123 "blocks" PROJ-456
/jira link PROJ-123 "relates to" PROJ-789
```

The skill also integrates git workflow — Claude will suggest branch names and commit formats based on the ticket.

### /confluence — Confluence Page Management

```bash
/confluence search "deployment guide"
/confluence search "runbook" DEV              # search in specific space
/confluence get 12345678                      # get page by ID
/confluence create DEV "Page Title" "Content"
/confluence create DEV "Child Page" "Content" 12345678  # with parent
/confluence update 12345678 "New content" 3   # update (must provide version)
/confluence my-pages                          # your recently edited pages
/confluence spaces                            # list all spaces
/confluence create-from-md DEV "Title" docs/file.md          # from markdown file
/confluence create-from-md DEV "Title" docs/file.md 12345678 # with parent
```

**Large markdown files (>20KB):** Use the Python script directly:
```bash
python3 ~/.claude/scripts/confluence-upload-large.py "DEV" "Page Title" "docs/large-file.md"
```

### /azure-devops — Azure DevOps Pull Requests

Auto-detects org/project/repo from your current git remote. Uses git credential manager — no stored credentials needed.

```bash
/azure-devops create-pr feature/my-branch main "PR Title" "Description"
/azure-devops list-prs                        # active PRs
/azure-devops list-prs completed              # completed PRs
/azure-devops my-prs                          # your open PRs
/azure-devops get-pr 42
/azure-devops update-pr 42 "New Title" "New Description"
/azure-devops add-reviewers 42 user@company.com user2@company.com
/azure-devops complete-pr 42 squash           # merge strategies: squash, merge, rebase
/azure-devops abandon-pr 42
```

### /skillify — Session to Skill Converter

Run at the end of any session where a repeatable workflow was discovered. Analyzes the conversation, asks 4 clarifying questions, generates a `SKILL.md`, and saves it to dotfiles (global) or the current project.

```bash
/skillify
```

### /tech-debt — End-of-Session Cleanup

Spawns 3 parallel agents to find duplication, dead code, and redundancy. Presents a report, fixes approved items one at a time with test verification after each, and commits if clean.

```bash
/tech-debt
```

### /ddup — Duplicate Issue Detector

Fetches a GitHub issue and all open issues via `gh` CLI. Claude scores each for semantic similarity (0–100). Reports all candidates ≥ 40, drafts a comment for the top match ≥ 70, and requires explicit confirmation before posting.

```bash
/ddup 123
```

### /verify-template — Project Verify Skill Generator

Run once when setting up Claude Code in a new project. Scans the codebase for test, lint, and run commands, confirms with you, then generates `.claude/skills/verify/SKILL.md` pre-filled with the discovered commands. Commit that file to the project repo.

```bash
/verify-template
```

## Claude Code Plugins

Plugins extend Claude Code with additional skills and workflows. Managed by Claude Code's plugin system — versioned and auto-updated independently of dotfiles.

For a full guide on what each plugin does, when to use it, and how they fit together as a workflow: **[docs/claude-code-workflow.md](docs/claude-code-workflow.md)**

**Marketplaces:**
- [claude-plugins-official](https://github.com/anthropics/claude-plugins-official) — Anthropic's official marketplace (built-in)
- [claude-code-skills](https://github.com/alirezarezvani/claude-skills) — Community marketplace (220+ skills)

Install on a new machine:
```bash
# Add community marketplace (registers as "claude-code-skills")
claude plugin marketplace add alirezarezvani/claude-skills

# Superpowers suite
claude plugin install superpowers@claude-plugins-official
claude plugin install engineering-skills@claude-code-skills
claude plugin install finance-skills@claude-code-skills
claude plugin install c-level-skills@claude-code-skills

# Development workflow
claude plugin install commit-commands@claude-plugins-official
claude plugin install code-review@claude-plugins-official
claude plugin install pr-review-toolkit@claude-plugins-official
claude plugin install skill-creator@claude-plugins-official

# Project maintenance
claude plugin install claude-md-management@claude-plugins-official
claude plugin install claude-code-setup@claude-plugins-official
claude plugin install security-guidance@claude-plugins-official
```

Update all plugins:
```bash
claude plugin update superpowers@claude-plugins-official
claude plugin update engineering-skills@claude-code-skills
claude plugin update finance-skills@claude-code-skills
claude plugin update c-level-skills@claude-code-skills
claude plugin update commit-commands@claude-plugins-official
claude plugin update code-review@claude-plugins-official
claude plugin update pr-review-toolkit@claude-plugins-official
claude plugin update skill-creator@claude-plugins-official
claude plugin update claude-md-management@claude-plugins-official
claude plugin update claude-code-setup@claude-plugins-official
claude plugin update security-guidance@claude-plugins-official
```

| Plugin | Source | What it adds |
|---|---|---|
| `superpowers` | official | Brainstorming, planning, subagent-driven development, TDD, code review workflows |
| `engineering-skills` | community | Architecture analysis, dependency analysis, architecture diagrams |
| `finance-skills` | community | Financial analysis and modelling skills |
| `c-level-skills` | community | Executive-level reporting and strategy skills |
| `commit-commands` | official | `/commit`, `/commit-push-pr` — auto-generates commit messages, pushes, opens PRs |
| `code-review` | official | `/code-review` — 4 parallel agents review PRs with confidence-scored findings |
| `pr-review-toolkit` | official | 6 specialized agents: comment accuracy, test coverage, silent failures, type design, general review, simplification |
| `skill-creator` | official | Create, improve, and benchmark skills; foundation for custom skill development |
| `claude-md-management` | official | `claude-md-improver` keeps CLAUDE.md accurate; `/revise-claude-md` captures session learnings |
| `claude-code-setup` | official | Scans a codebase and recommends hooks, skills, MCP servers tailored to it |
| `security-guidance` | official | Always-on PreToolUse hook — warns about security issues on every file edit |

---

## Atlassian Scripts (Terminal)

Scripts can also be called directly from the terminal without Claude:

```bash
bash ~/.claude/scripts/jira-rest-api.sh mine
bash ~/.claude/scripts/jira-rest-api.sh get PROJ-123
bash ~/.claude/scripts/confluence-rest-api.sh search "runbook"
bash ~/.claude/scripts/azure-devops-rest-api.sh my-prs
```

### Credentials

Stored in `~/.atlassian/credentials` (gitignored). Set up interactively:
```bash
bash ~/.claude/scripts/setup-credentials-interactive.sh
```

Or manually:
```bash
cp ~/.claude/atlassian/credentials.template ~/.atlassian/credentials
nano ~/.atlassian/credentials
chmod 600 ~/.atlassian/credentials
```

The credentials file sets:
```bash
ATLASSIAN_EMAIL="you@company.com"
ATLASSIAN_API_TOKEN="your-token"
JIRA_URL="https://yourcompany.atlassian.net"
CONFLUENCE_URL="https://yourcompany.atlassian.net/wiki"
```

Get an API token at: https://id.atlassian.com/manage-profile/security/api-tokens

---

## Repo Structure

```
dotfiles/
├── install.sh                      # Install/update script (--claude, --shell, --config, --only, --list)
├── winget-packages.json            # Tool manifest for new machines
├── .gitattributes                  # Enforces LF line endings for shell files
├── CLAUDE.md                       # Claude Code behavior instructions
│
├── shell/
│   ├── .bashrc                     # SSH agent, shell options, history, PATH
│   ├── .bash_profile               # All aliases, functions, tool config (portable)
│   ├── .gitconfig                  # Full git config (identity via ~/.gitconfig.local)
│   └── starship.toml               # Prompt config
│
├── config/
│   ├── lazygit.yml                 # lazygit theme and key config
│   └── lazydocker.yml              # lazydocker theme and display config
│
├── windows/
│   └── terminal-settings.json      # Windows Terminal: theme, font, keybindings, profiles
│
└── claude/
    ├── scripts/
    │   ├── jira-rest-api.sh            # Jira CRUD operations
    │   ├── confluence-rest-api.sh      # Confluence page operations
    │   ├── azure-devops-rest-api.sh    # Azure DevOps PR operations
    │   ├── atlassian-common.sh         # Shared credential loading
    │   ├── confluence-upload-large.py  # Large markdown → Confluence upload
    │   ├── jira-create-from-template.py # Jira issues from YAML templates
    │   ├── create-issue-link.sh        # Jira issue linking
    │   ├── setup-credentials-interactive.sh
    │   └── ATLASSIAN_SETUP.md
    ├── skills/
    │   ├── jira/                   # /jira Claude skill
    │   ├── confluence/             # /confluence Claude skill
    │   └── azure-devops/           # /azure-devops Claude skill
    ├── agents/                     # User-level agents (available in all projects)
    ├── commands/                   # Custom slash commands (available in all projects)
    └── atlassian/
        └── credentials.template    # Template for ~/.atlassian/credentials
```

### Installed locations

```
shell/              → $HOME  (~/.bashrc, ~/.bash_profile, ~/.gitconfig)
shell/starship.toml → ~/.config/starship.toml
config/lazygit.yml    → ~/.config/lazygit/config.yml
config/lazydocker.yml → ~/.config/lazydocker/config.yml
windows/terminal-settings.json → %LOCALAPPDATA%\...\LocalState\settings.json
claude/scripts/     → ~/.claude/scripts/
claude/skills/      → ~/.claude/skills/
claude/agents/      → ~/.claude/agents/
claude/commands/    → ~/.claude/commands/
claude/atlassian/   → ~/.claude/atlassian/
```

---

## Machine-specific Files (never committed)

| File | Purpose |
|---|---|
| `~/.gitconfig.local` | Git identity: name and email |
| `~/.bashrc.local` | Machine-specific aliases, paths, env vars |
| `~/.atlassian/credentials` | Jira/Confluence API credentials |
| `~/.ssh/config` | SSH multi-account routing |

---

## Making Changes

**Shell aliases/functions** — edit in the repo, then install:
```bash
vim ~/repos/dotfiles/shell/.bash_profile
bash ~/repos/dotfiles/install.sh
source ~/.bash_profile
```

**Claude scripts** — edit in the repo, then install:
```bash
vim ~/repos/dotfiles/claude/scripts/jira-rest-api.sh
bash ~/repos/dotfiles/install.sh --only jira
```

**Adding a new tool** — install it, then update the manifest:
```bash
winget install SomePublisher.SomeTool
winget export -o ~/repos/dotfiles/winget-packages.json
cd ~/repos/dotfiles && git add winget-packages.json && git commit -m "feat: add SomeTool"
git push
```

---

## Security

**Never commit:**
- `~/.atlassian/credentials` (API tokens)
- `~/.gitconfig.local` (personal email)
- `~/.bashrc.local` (work paths)
- `~/.ssh/` (private keys)

**Safe to commit:**
- Scripts (no hardcoded secrets — credentials loaded from env)
- Skills and templates
- Shell config (company-specific aliases excluded)

---

## Troubleshooting

**Shell changes not visible after install:**
```bash
source ~/.bash_profile
```

**Wrong git identity on commits:**
```bash
cat ~/.gitconfig.local    # verify file exists with correct email
git config user.email     # verify git picks it up
```

**Atlassian scripts fail with auth error:**
```bash
cat ~/.atlassian/credentials    # verify file exists
bash ~/.claude/scripts/setup-credentials-interactive.sh  # re-run setup
```

**SSH authenticates as wrong GitHub account:**
```bash
ssh -T git@github-work      # test which account is used
ssh -T git@github-personal
cat ~/.ssh/config            # verify IdentityFile mapping
```

**Rollback after bad install:**
```bash
ls ~/.claude/.backup-*      # find latest backup
cp -r ~/.claude/.backup-TIMESTAMP/* ~/.claude/
```
