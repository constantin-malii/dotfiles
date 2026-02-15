# Personal Dotfiles

Personal configuration files and scripts for Claude Code, shell, and development tools.

## Installation

### First Time Setup

```bash
# 1. Clone this repo (if not already)
git clone git@github.com:YOUR_USERNAME/dotfiles.git ~/repos/dotfiles

# 2. Run install script
cd ~/repos/dotfiles
bash install.sh

# 3. Setup Atlassian credentials (interactive)
bash ~/.claude/scripts/setup-credentials-interactive.sh
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
├── README.md                       # This file
│
├── claude/
│   ├── scripts/
│   │   ├── atlassian-common.sh    # Shared validation
│   │   ├── jira-rest-api.sh       # Jira operations
│   │   ├── confluence-rest-api.sh # Confluence operations
│   │   └── ATLASSIAN_SETUP.md     # Setup guide
│   │
│   ├── skills/
│   │   ├── jira/                  # Generic Jira skill
│   │   ├── confluence/            # Generic Confluence skill
│   │   ├── jira-symend/           # Symend-specific Jira
│   │   └── confluence-symend/     # Symend-specific Confluence
│   │
│   └── atlassian/
│       └── credentials.template   # Credentials template
│
└── shell/
    └── (future: bashrc, aliases, etc.)
```

## Installed Location

Files are copied to:
```
~/.claude/
├── scripts/       # From claude/scripts/
├── skills/        # From claude/skills/
└── atlassian/     # From claude/atlassian/
```

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
