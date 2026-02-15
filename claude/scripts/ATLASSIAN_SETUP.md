# Atlassian API Setup Guide

This guide explains how to configure authentication for Jira and Confluence REST API scripts.

## Credential Priority

The scripts check for credentials in this order:
1. **Environment variables** (highest priority)
2. **Config file** (`~/.atlassian/credentials`)
3. **Fail** if neither exists

## Step 1: Generate API Token

1. Go to https://id.atlassian.com/manage-profile/security/api-tokens
2. Click **Create API token**
3. Give it a name (e.g., "Claude Scripts")
4. Copy the token (you won't see it again!)

## Step 2: Choose Setup Method

### Option A: Config File (Recommended)

**Best for**: Personal use, multiple machines, easy management

**Quick Setup** (if migrating from hardcoded credentials):
```bash
# Run the setup script (already has your current token)
bash ~/.claude/scripts/setup-atlassian-config.sh

# Test it works
bash ~/.claude/scripts/jira-rest-api.sh mine

# Delete setup script (contains your token!)
rm ~/.claude/scripts/setup-atlassian-config.sh
```

**Manual Setup**:
```bash
# Create config directory
mkdir -p ~/.atlassian

# Create credentials file
cat > ~/.atlassian/credentials << 'EOF'
[default]
email = your.email@symend.com
api_token = your-api-token-here
EOF

# Secure the file
chmod 600 ~/.atlassian/credentials
```

**Advantages:**
- ✅ Single file to manage
- ✅ Easy to backup/restore
- ✅ Works across all shells
- ✅ Can store multiple profiles (future)

### Option B: Environment Variables

**Best for**: CI/CD, temporary access, security-sensitive environments

Add to your shell profile (`~/.bashrc` or `~/.zshrc`):

```bash
# Atlassian API credentials
export ATLASSIAN_EMAIL="your.email@symend.com"
export ATLASSIAN_API_TOKEN="your-api-token-here"
```

Then reload your shell:
```bash
source ~/.bashrc  # or ~/.zshrc
```

**Advantages:**
- ✅ No config file on disk
- ✅ Easy to override per-session
- ✅ Standard for CI/CD pipelines

### Option C: Hybrid (Both)

You can use both! Environment variables override config file.

**Example use case:**
- Config file for personal token
- Environment variables for service account in CI/CD

## Step 3: Verify Setup

Test your configuration:

```bash
# Check variables are set
echo $ATLASSIAN_EMAIL
echo $ATLASSIAN_API_TOKEN

# Test Jira access
bash ~/.claude/scripts/jira-rest-api.sh mine

# Test Confluence access
bash ~/.claude/scripts/confluence-rest-api.sh my-pages
```

## Optional: Service URLs

Override default URLs if needed:

```bash
export JIRA_URL="https://your-instance.atlassian.net"
export CONFLUENCE_URL="https://your-instance.atlassian.net/wiki"
```

## Security Best Practices

✅ **Do:**
- Store credentials in your shell profile (not committed to git)
- Use API tokens (never passwords)
- Rotate tokens periodically
- Keep token permissions minimal

❌ **Don't:**
- Hardcode credentials in scripts
- Share tokens in chat or email
- Commit tokens to version control
- Use tokens in CI/CD (use service accounts instead)

## Troubleshooting

### Error: "ATLASSIAN_EMAIL environment variable not set"

Your environment variables aren't configured. Follow Step 2 above.

### Error: "401 Unauthorized"

Your API token is invalid or expired. Generate a new token (Step 1).

### Error: "403 Forbidden"

Your account doesn't have permission for the requested operation.

## Token Rotation

If you need to rotate your token:

1. Generate a new token (Step 1)
2. Update `ATLASSIAN_API_TOKEN` in your shell profile
3. Reload: `source ~/.bashrc`
4. Revoke old token at https://id.atlassian.com/manage-profile/security/api-tokens
