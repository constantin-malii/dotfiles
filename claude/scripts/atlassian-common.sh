#!/bin/bash
# Shared Atlassian authentication and validation
# Source this file in scripts that need Atlassian API access
#
# Credential Priority:
# 1. Environment variables (ATLASSIAN_EMAIL, ATLASSIAN_API_TOKEN)
# 2. Config file (~/.atlassian/credentials)
# 3. Fail if neither exists

CONFIG_FILE="$HOME/.atlassian/credentials"

# Load credentials from config file
load_credentials_from_config() {
    if [[ ! -f "$CONFIG_FILE" ]]; then
        return 1
    fi

    # Parse INI-style config file
    local section=""
    while IFS='=' read -r key value; do
        # Trim whitespace
        key=$(echo "$key" | xargs)
        value=$(echo "$value" | xargs)

        # Skip comments and empty lines
        [[ "$key" =~ ^#.*$ ]] && continue
        [[ -z "$key" ]] && continue

        # Track sections
        if [[ "$key" =~ ^\[.*\]$ ]]; then
            section="$key"
            continue
        fi

        # Load credentials from [default] section
        if [[ "$section" == "[default]" ]]; then
            case "$key" in
                email)
                    ATLASSIAN_EMAIL="$value"
                    ;;
                api_token)
                    ATLASSIAN_API_TOKEN="$value"
                    ;;
                jira_url)
                    JIRA_URL="$value"
                    ;;
                confluence_url)
                    CONFLUENCE_URL="$value"
                    ;;
            esac
        fi
    done < "$CONFIG_FILE"

    return 0
}

# Validate and load credentials
validate_atlassian_credentials() {
    # Priority 1: Check environment variables
    if [[ -z "${ATLASSIAN_EMAIL}" ]] || [[ -z "${ATLASSIAN_API_TOKEN}" ]]; then
        # Priority 2: Try loading from config file
        load_credentials_from_config
    fi

    # Validate that we have credentials
    local missing=0

    if [[ -z "${ATLASSIAN_EMAIL}" ]]; then
        echo "ERROR: ATLASSIAN_EMAIL not found" >&2
        missing=1
    fi

    if [[ -z "${ATLASSIAN_API_TOKEN}" ]]; then
        echo "ERROR: ATLASSIAN_API_TOKEN not found" >&2
        missing=1
    fi

    # Validate URLs are configured
    if [[ -z "${JIRA_URL}" ]]; then
        echo "ERROR: JIRA_URL not found" >&2
        missing=1
    fi

    if [[ -z "${CONFLUENCE_URL}" ]]; then
        echo "ERROR: CONFLUENCE_URL not found" >&2
        missing=1
    fi

    if [[ $missing -eq 1 ]]; then
        echo "" >&2
        echo "Credentials can be provided via:" >&2
        echo "  1. Environment variables (recommended for CI/CD)" >&2
        echo "  2. Config file: ~/.atlassian/credentials" >&2
        echo "" >&2
        echo "Setup instructions: ~/.claude/scripts/ATLASSIAN_SETUP.md" >&2
        exit 1
    fi

    # Export for use by calling scripts
    export ATLASSIAN_EMAIL
    export ATLASSIAN_API_TOKEN
    export JIRA_URL
    export CONFLUENCE_URL
}

# Call validation
validate_atlassian_credentials
