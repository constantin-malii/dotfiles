# Push Dotfiles to Personal GitHub

## Step 1: Create Repository on GitHub

Go to: https://github.com/new

**Settings:**
- Owner: `constantin-malii` (your personal account)
- Repository name: `dotfiles`
- Description: "Personal dotfiles and development scripts"
- Visibility: **Private** (recommended for dotfiles)
- ❌ Don't initialize with README (we already have files)

Click "Create repository"

## Step 2: Push to Personal GitHub

```bash
cd /d/repos/dotfiles

# Add your personal GitHub as remote
git remote add origin git@github.com:constantin-malii/dotfiles.git

# Push to your personal account
git push -u origin main
```

## Step 3: Verify

Check: https://github.com/constantin-malii/dotfiles

## Future: New Machine Setup

```bash
# Clone from your personal GitHub
git clone git@github.com:constantin-malii/dotfiles.git ~/repos/dotfiles

# Install
cd ~/repos/dotfiles
bash install.sh

# Setup credentials (interactive)
bash ~/.claude/scripts/setup-credentials-interactive.sh
```

## Note

Your current `gh` CLI is still logged into company account (constantinmalii).
This is fine! You can push to your personal repo using git directly with SSH keys.

If you want to use `gh` CLI with your personal account later:
```bash
gh auth login
# Choose: GitHub.com
# Choose: Login with a web browser
# Login with malii.constantin@gmail.com
```
