#!/bin/bash
# Get Jira issue links
# Requires environment variables: ATLASSIAN_EMAIL, ATLASSIAN_API_TOKEN

# Source shared Atlassian validation
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/atlassian-common.sh"

# Set service-specific variables
JIRA_USER="${ATLASSIAN_EMAIL}"
JIRA_TOKEN="${ATLASSIAN_API_TOKEN}"
# JIRA_URL loaded from config/env by atlassian-common.sh

ISSUE_KEY=$1

curl -s -X GET \
  "${JIRA_URL}/rest/api/3/issue/${ISSUE_KEY}?fields=issuelinks" \
  -u "${JIRA_USER}:${JIRA_TOKEN}" \
  -H "Content-Type: application/json" | jq '.fields.issuelinks[] | {id: .id, type: .type.name, inward: .inwardIssue.key?, outward: .outwardIssue.key?}'

