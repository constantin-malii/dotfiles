# Personal Dotfiles

Personal configuration files and scripts for Claude Code, shell, and development tools.

## Quick Links

- 🚀 **[Multi-Machine Setup Guide](MULTI_MACHINE_SETUP.md)** - Installing on machines with different GitHub accounts
- 📝 **[Push to Personal GitHub](PUSH_TO_PERSONAL_GITHUB.md)** - Initial setup guide

## Installation

### First Time Setup

```bash
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
```

### Machine-specific config

Two files are **never committed** — create them per machine:

**`~/.gitconfig.local`** — your git identity:
```ini
[user]
    name = Your Name
    email = you@example.com
```

**`~/.bashrc.local`** — machine-specific aliases and paths:
```bash
# Example work machine overrides
export REPOS_DIR=/c/Users/YourName/source/repos
alias prj='cd $REPOS_DIR'
```

### Updating

When you pull new changes from this repo:

```bash
# 1. Pull latest changes
cd ~/repos/dotfiles
git pull

# 2. Run install script again (creates backup automatically)
bash install.sh
```

**Safe updates:**
- ✅ Automatically backs up existing files
- ✅ Never overwrites your credentials file
- ✅ Preserves executable permissions
- ✅ Shows backup location for rollback

## Structure

```
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
```

## Installed Location

Files are copied to:
```
~/.claude/
├── scripts/       # From claude/scripts/ (*.sh, *.py, *.md)
├── skills/        # From claude/skills/
└── atlassian/     # From claude/atlassian/
```

## Python Scripts

Some operations require Python scripts for advanced functionality:

### Dependencies

Install required Python packages:
```bash
# For large Confluence file uploads
pip install md2cf mistune requests

# For Jira template system
pip install requests pyyaml
```

### confluence-upload-large.py

**Purpose:** Upload large markdown files to Confluence (handles files > 20KB that exceed bash command-line argument limits).

**Usage:**
```bash
export CONFLUENCE_EMAIL="your-email@example.com"
export CONFLUENCE_API_TOKEN="your-api-token"
export CONFLUENCE_URL="https://your-company.atlassian.net/wiki"

python3 ~/.claude/scripts/confluence-upload-large.py "SPACE" "Page Title" "docs/large-file.md"
```

**When to use:**
- Markdown files larger than ~20KB
- Complex documentation with many images/code blocks
- Automatic markdown → Confluence HTML conversion

### jira-create-from-template.py

**Purpose:** Create/update Jira issues from YAML templates with proper ADF (Atlassian Document Format) formatting.

**Usage:**
```bash
export ATLASSIAN_EMAIL="your-email@example.com"
export ATLASSIAN_API_TOKEN="your-api-token"
export JIRA_URL="https://your-company.atlassian.net"

python3 ~/.claude/scripts/jira-create-from-template.py PROJ-123 ~/.claude/jira-templates/stories/my-story.yaml
```

**Features:**
- Supports Epic, Story, and Bug templates
- Rich formatting with emojis, tables, code blocks
- Automatic parent linking
- Custom field support (e.g., Value Stream)

**Template locations:**
- `~/.claude/jira-templates/epics/` - Epic templates
- `~/.claude/jira-templates/stories/` - Story templates
- `~/.claude/jira-templates/bugs/` - Bug templates

## Workflow

### Making Changes

**Option 1: Edit in repo (recommended)**
```bash
# Edit files in the repo
vim ~/repos/dotfiles/claude/scripts/jira-rest-api.sh

# Test locally
bash ~/repos/dotfiles/claude/scripts/jira-rest-api.sh mine

# Commit and push
git add -A
git commit -m "Update jira script"
git push

# Install to ~/.claude/
bash ~/repos/dotfiles/install.sh
```

**Option 2: Edit installed files**
```bash
# Edit installed file
vim ~/.claude/scripts/jira-rest-api.sh

# Copy back to repo
cp ~/.claude/scripts/jira-rest-api.sh ~/repos/dotfiles/claude/scripts/

# Commit
cd ~/repos/dotfiles
git add -A
git commit -m "Update jira script"
git push
```

### New Machine Setup

```bash
# 1. Clone dotfiles
git clone git@github.com:YOUR_USERNAME/dotfiles.git ~/repos/dotfiles

# 2. Install
cd ~/repos/dotfiles
bash install.sh

# 3. Setup credentials (interactive - will prompt for email/token)
bash ~/.claude/scripts/setup-credentials-interactive.sh
```

**Alternative: Manual setup**
```bash
cp ~/.atlassian/credentials.template ~/.atlassian/credentials
nano ~/.atlassian/credentials  # Edit with your actual credentials
chmod 600 ~/.atlassian/credentials
```

## Security

**Never commit:**
- ❌ Actual credentials (`~/.atlassian/credentials`)
- ❌ API tokens
- ❌ Any secrets

**Safe to commit:**
- ✅ Scripts (no hardcoded secrets)
- ✅ Skills
- ✅ Templates
- ✅ Documentation

## Troubleshooting

### Rollback After Update

If an update breaks something:
```bash
# Find backup directory
ls -lt ~/.claude/.backup-*

# Restore from backup
cp -r ~/.claude/.backup-TIMESTAMP/* ~/.claude/
```

### Credentials Not Working

```bash
# Check if file exists
cat ~/.atlassian/credentials

# Re-run setup
bash ~/.claude/scripts/setup-atlassian-config.sh
```

### Permissions Issue

```bash
# Fix script permissions
chmod +x ~/.claude/scripts/*.sh
```

## Contributing

This is a personal repo, but improvements are welcome:
1. Fork it
2. Make changes
3. Test thoroughly
4. Submit PR (if you want to share improvements)

## License

Personal use only.
