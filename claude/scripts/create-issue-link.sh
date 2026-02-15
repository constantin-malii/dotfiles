#!/bin/bash
# Create Jira issue link (Blocks relationship)
# Requires environment variables: ATLASSIAN_EMAIL, ATLASSIAN_API_TOKEN

# Source shared Atlassian validation
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/atlassian-common.sh"

# Set service-specific variables
JIRA_USER="${ATLASSIAN_EMAIL}"
JIRA_TOKEN="${ATLASSIAN_API_TOKEN}"
# JIRA_URL loaded from config/env by atlassian-common.sh

BLOCKED_ISSUE=$1
BLOCKER_ISSUE=$2

curl -s -X POST \
  "${JIRA_URL}/rest/api/3/issueLink" \
  -u "${JIRA_USER}:${JIRA_TOKEN}" \
  -H "Content-Type: application/json" \
  -d "{
    \"type\": {
      \"name\": \"Blocks\"
    },
    \"inwardIssue\": {
      \"key\": \"${BLOCKED_ISSUE}\"
    },
    \"outwardIssue\": {
      \"key\": \"${BLOCKER_ISSUE}\"
    }
  }"

echo ""
