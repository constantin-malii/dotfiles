# Multi-Machine Setup Guide

This guide covers installing your dotfiles on machines configured with different GitHub accounts (company vs personal).

## The Problem

You want to clone your **personal dotfiles** (`constantin-malii/dotfiles`) on a machine that's already configured with a **different company GitHub account**.

## Solutions

### Option 1: Make Repo Public (Simplest)

**When to use:** You don't mind your dotfiles being publicly visible (no secrets stored anyway).

**Setup:**
1. On GitHub: Repository Settings → Change visibility → **Public**
2. Clone on any machine (no auth needed):
   ```bash
   git clone https://github.com/constantin-malii/dotfiles.git ~/repos/dotfiles
   cd ~/repos/dotfiles
   bash install.sh
   ```

**Pros:**
- ✅ Works on any machine instantly
- ✅ No authentication hassle
- ✅ Can share your setup with others

**Cons:**
- ❌ Dotfiles are publicly visible (but contain no secrets)

---

### Option 2: Personal Access Token (One-Time Auth)

**When to use:** Repo stays private, quick setup for one-time clone.

**Setup:**
1. **Create token** (do this once):
   - Go to: https://github.com/settings/tokens
   - Login with: `malii.constantin@gmail.com`
   - **Generate new token (classic)**
   - Name: `dotfiles-readonly`
   - Expiration: No expiration (or long duration)
   - Scopes: ✅ `repo` (Full control - needed for private repos)
   - **Copy the token** (save it somewhere safe!)

2. **Clone with token** (on new machine):
   ```bash
   git clone https://YOUR_TOKEN@github.com/constantin-malii/dotfiles.git ~/repos/dotfiles
   cd ~/repos/dotfiles
   bash install.sh
   ```

3. **After clone, remove token from remote** (for security):
   ```bash
   cd ~/repos/dotfiles
   git remote set-url origin https://github.com/constantin-malii/dotfiles.git
   ```

4. **Future pulls** use machine's default git credentials:
   ```bash
   git pull  # Uses whatever account is configured
   ```

**Pros:**
- ✅ Repo stays private
- ✅ Works on any machine
- ✅ Token can be reused across machines

**Cons:**
- ❌ Need to manage token securely
- ❌ Token in command history (use carefully)

**Security tip:** Clear token from history:
```bash
history -d $(history | tail -2 | head -1 | awk '{print $1}')
```

---

### Option 3: SSH Key Per Machine (Most Secure)

**When to use:** Best practice for multiple machines, permanent setup.

**Setup (on each new machine):**

1. **Generate SSH key** (if not exists):
   ```bash
   # Check if key exists
   ls ~/.ssh/id_ed25519.pub

   # If not, generate new key
   ssh-keygen -t ed25519 -C "malii.constantin@gmail.com"
   # Press Enter to accept defaults
   # Optional: add passphrase for extra security
   ```

2. **Copy public key**:
   ```bash
   cat ~/.ssh/id_ed25519.pub
   # Copy the output
   ```

3. **Add to personal GitHub**:
   - Go to: https://github.com/settings/ssh/new
   - Login with: `malii.constantin@gmail.com`
   - Title: `Machine Name - dotfiles` (e.g., "Work Laptop 2")
   - Key: Paste the public key
   - Click **Add SSH key**

4. **Test connection**:
   ```bash
   ssh -T git@github.com
   # Should say: "Hi constantin-malii! You've successfully authenticated..."
   ```

5. **Clone**:
   ```bash
   git clone git@github.com:constantin-malii/dotfiles.git ~/repos/dotfiles
   cd ~/repos/dotfiles
   bash install.sh
   ```

**Pros:**
- ✅ Most secure (no tokens in commands)
- ✅ Works permanently per machine
- ✅ Standard practice
- ✅ Can revoke access per machine

**Cons:**
- ❌ Requires setup on each machine
- ❌ More steps

**Note:** This works even if the machine's git is configured for a company account! SSH keys are separate from git config.

---

### Option 4: SSH Config for Multiple Accounts (Advanced)

**When to use:** You frequently switch between personal and company repos on the same machine.

**Setup:**

1. **Generate separate keys** (if not exists):
   ```bash
   # Personal key
   ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_personal -C "malii.constantin@gmail.com"

   # Company key (if separate)
   ssh-keygen -t ed25519 -f ~/.ssh/id_ed25519_company -C "you@company.com"
   ```

2. **Configure SSH** (`~/.ssh/config`):
   ```bash
   # Personal GitHub
   Host github-personal
     HostName github.com
     User git
     IdentityFile ~/.ssh/id_ed25519_personal
     IdentitiesOnly yes

   # Company GitHub (default)
   Host github.com
     HostName github.com
     User git
     IdentityFile ~/.ssh/id_ed25519_company
     IdentitiesOnly yes
   ```

3. **Add keys to respective GitHub accounts**:
   - Add `id_ed25519_personal.pub` to https://github.com/settings/ssh (personal)
   - Add `id_ed25519_company.pub` to company GitHub

4. **Clone personal repos** using custom host:
   ```bash
   git clone git@github-personal:constantin-malii/dotfiles.git ~/repos/dotfiles
   ```

5. **Clone company repos** normally:
   ```bash
   git clone git@github.com:company/repo.git
   ```

**Pros:**
- ✅ Clean separation of accounts
- ✅ Both accounts work simultaneously
- ✅ No confusion about which account

**Cons:**
- ❌ More complex setup
- ❌ Must remember to use `github-personal` for personal repos

---

## After Cloning: Installation

Regardless of which option you used, after cloning:

```bash
# 1. Install dotfiles
cd ~/repos/dotfiles
bash install.sh

# 2. Configure credentials for this machine
bash ~/.claude/scripts/setup-credentials-interactive.sh
# Prompts for:
# - Email (for this machine's company)
# - API Token (for this machine's company)
# - Jira URL (for this machine's company)
# - Confluence URL (for this machine's company)

# 3. Test
bash ~/.claude/scripts/jira-rest-api.sh mine
```

## Updating Dotfiles on Any Machine

Once set up, updating is simple:

```bash
cd ~/repos/dotfiles
git pull
bash install.sh  # Re-install updated files
```

## Recommended Approach

**For most users:**
- First time: Use **Option 2** (Personal Access Token) - quick and easy
- Long term: Use **Option 3** (SSH keys per machine) - most secure and permanent

**For public sharing:**
- Use **Option 1** (Public repo) - if you don't mind sharing your setup

**For power users:**
- Use **Option 4** (SSH config) - if you manage multiple accounts frequently

## FAQ

**Q: Can I use my dotfiles on both work and personal machines?**
A: Yes! Each machine gets its own credentials config (`~/.atlassian/credentials`).

**Q: Will this mess up my company GitHub setup?**
A: No. SSH keys and git config are separate. Adding a personal SSH key doesn't affect company access.

**Q: What if I don't want to store my token?**
A: Use Option 3 (SSH keys). Generate once per machine, no tokens needed.

**Q: Can I switch between options later?**
A: Yes! You can start with Option 2 (token) and switch to Option 3 (SSH) later.

## Security Reminders

- ✅ Never commit tokens or credentials to the repo
- ✅ Use `.gitignore` to exclude `~/.atlassian/credentials`
- ✅ Rotate tokens periodically
- ✅ Use SSH keys instead of tokens when possible
- ✅ Use different credentials on each machine (don't share)
