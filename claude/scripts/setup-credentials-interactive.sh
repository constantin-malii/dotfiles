#!/bin/bash
# Interactive Atlassian Credentials Setup
# Prompts for credentials and creates ~/.atlassian/credentials

set -e

CONFIG_DIR="$HOME/.atlassian"
CONFIG_FILE="$CONFIG_DIR/credentials"

echo "=========================================="
echo "Atlassian API Credentials Setup"
echo "=========================================="
echo ""

# Check if config already exists
if [[ -f "$CONFIG_FILE" ]]; then
    echo "⚠️  Credentials file already exists: $CONFIG_FILE"
    echo ""
    read -p "Overwrite existing credentials? (y/N): " -n 1 -r
    echo
    if [[ ! $REPLY =~ ^[Yy]$ ]]; then
        echo "Setup cancelled. No changes made."
        exit 0
    fi
    # Backup existing
    cp "$CONFIG_FILE" "$CONFIG_FILE.backup.$(date +%Y%m%d-%H%M%S)"
    echo "✅ Backed up existing file"
    echo ""
fi

# Prompt for email
echo "Enter your Atlassian email:"
read -p "Email: " atlassian_email

if [[ -z "$atlassian_email" ]]; then
    echo "ERROR: Email cannot be empty"
    exit 1
fi

# Prompt for API token (hidden input)
echo ""
echo "Enter your Atlassian API token:"
echo "(Get token from: https://id.atlassian.com/manage-profile/security/api-tokens)"
read -s -p "Token: " atlassian_token
echo ""

if [[ -z "$atlassian_token" ]]; then
    echo "ERROR: Token cannot be empty"
    exit 1
fi

# Prompt for Jira URL
echo ""
echo "Enter your Jira URL:"
echo "(Example: https://yourcompany.atlassian.net)"
read -p "Jira URL: " jira_url

if [[ -z "$jira_url" ]]; then
    echo "ERROR: Jira URL cannot be empty"
    exit 1
fi

# Prompt for Confluence URL
echo ""
echo "Enter your Confluence URL:"
echo "(Example: https://yourcompany.atlassian.net/wiki)"
read -p "Confluence URL: " confluence_url

if [[ -z "$confluence_url" ]]; then
    echo "ERROR: Confluence URL cannot be empty"
    exit 1
fi

# Create config directory
mkdir -p "$CONFIG_DIR"

# Create config file
cat > "$CONFIG_FILE" << EOF
# Atlassian API Credentials
# This file stores your Atlassian credentials
# Environment variables take precedence over this file

[default]
email = $atlassian_email
api_token = $atlassian_token
jira_url = $jira_url
confluence_url = $confluence_url
EOF

# Secure the file
chmod 600 "$CONFIG_FILE" 2>/dev/null || echo "⚠️  Could not set file permissions (Windows?)"

echo ""
echo "=========================================="
echo "✅ Credentials saved successfully!"
echo "=========================================="
echo ""
echo "File: $CONFIG_FILE"
echo "Permissions: $(ls -l "$CONFIG_FILE" 2>/dev/null | awk '{print $1}')"
echo ""

# Offer to test
read -p "Test credentials now? (Y/n): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Nn]$ ]]; then
    echo ""
    echo "Testing Jira access..."
    http_code=$(curl -s -o /dev/null -w "%{http_code}" \
        -u "${email}:${api_token}" \
        "${jira_url}/rest/api/2/myself")
    if [[ "$http_code" =~ ^2 ]]; then
        echo ""
        echo "✅ Credentials work! Setup complete."
    else
        echo ""
        echo "❌ Test failed (HTTP $http_code). Please check:"
        echo "  1. Email is correct"
        echo "  2. API token is valid"
        echo "  3. You have Jira access"
        echo ""
        echo "To fix: Run this script again"
    fi
else
    echo ""
    echo "To test manually:"
    echo "  bash ~/.claude/scripts/jira-rest-api.sh mine"
fi

echo ""
echo "Setup complete! 🎉"
