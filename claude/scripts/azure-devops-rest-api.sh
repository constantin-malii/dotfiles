#!/bin/bash
# Azure DevOps REST API wrapper - Pull Request operations
# Auth: Uses git credential manager (no stored credentials needed)
# Auto-detects org/project/repo from git remote origin

set -euo pipefail

# ============================================================
# Authentication & Repository Detection
# ============================================================

get_pat() {
    local url
    url=$(git remote get-url origin 2>/dev/null) || {
        echo "ERROR: Not in a git repo or no remote 'origin'" >&2
        exit 1
    }

    local host
    host=$(echo "$url" | sed -n 's|https://\([^/]*\)/.*|\1|p')
    if [[ -z "$host" ]]; then
        echo "ERROR: Could not parse host from remote URL: $url" >&2
        exit 1
    fi

    PAT=$(printf "host=%s\nprotocol=https\n" "$host" | git credential-manager get 2>/dev/null | grep password | cut -d= -f2)
    if [[ -z "$PAT" ]]; then
        echo "ERROR: Could not get PAT from git credential manager for $host" >&2
        echo "Ensure git credentials are configured for $host" >&2
        exit 1
    fi
}

url_encode() {
    # Encode spaces as %20, preserve other URL-safe chars
    echo "$1" | sed 's/ /%20/g'
}

detect_repo_info() {
    local url
    url=$(git remote get-url origin 2>/dev/null)

    # Format 1: https://org.visualstudio.com/Project/_git/Repo
    # Format 2: https://dev.azure.com/org/Project/_git/Repo
    if echo "$url" | grep -q 'visualstudio.com'; then
        ORG_HOST=$(echo "$url" | sed -n 's|https://\([^/]*\)/.*|\1|p')
        PROJECT=$(echo "$url" | sed -n 's|https://[^/]*/\([^/]*\)/_git/.*|\1|p')
        REPO=$(echo "$url" | sed -n 's|https://[^/]*/[^/]*/_git/\(.*\)|\1|p')
        BASE_API="https://${ORG_HOST}/$(url_encode "$PROJECT")/_apis/git/repositories/$(url_encode "$REPO")"
        WEB_URL="https://${ORG_HOST}/$(url_encode "$PROJECT")/_git/$(url_encode "$REPO")"
    elif echo "$url" | grep -q 'dev.azure.com'; then
        ORG=$(echo "$url" | sed -n 's|https://dev.azure.com/\([^/]*\)/.*|\1|p')
        PROJECT=$(echo "$url" | sed -n 's|https://dev.azure.com/[^/]*/\([^/]*\)/_git/.*|\1|p')
        REPO=$(echo "$url" | sed -n 's|https://dev.azure.com/[^/]*/[^/]*/_git/\(.*\)|\1|p')
        BASE_API="https://dev.azure.com/${ORG}/$(url_encode "$PROJECT")/_apis/git/repositories/$(url_encode "$REPO")"
        WEB_URL="https://dev.azure.com/${ORG}/$(url_encode "$PROJECT")/_git/$(url_encode "$REPO")"
    else
        echo "ERROR: Unrecognized Azure DevOps URL format: $url" >&2
        echo "Expected: https://org.visualstudio.com/Project/_git/Repo" >&2
        echo "      or: https://dev.azure.com/org/Project/_git/Repo" >&2
        exit 1
    fi

    # Strip .git suffix if present
    REPO="${REPO%.git}"
    BASE_API="${BASE_API%.git}"
    WEB_URL="${WEB_URL%.git}"
}

# Initialize auth and repo info
get_pat
detect_repo_info

# ============================================================
# API Helper
# ============================================================

api_call() {
    local method="$1"
    local endpoint="$2"
    local data="${3:-}"

    local args=(-s -u ":${PAT}" -H "Content-Type: application/json")

    case "$method" in
        GET)    args+=("${BASE_API}/${endpoint}") ;;
        POST)   args+=(-X POST --data "$data" "${BASE_API}/${endpoint}") ;;
        PATCH)  args+=(-X PATCH --data "$data" "${BASE_API}/${endpoint}") ;;
        PUT)    args+=(-X PUT --data "$data" "${BASE_API}/${endpoint}") ;;
        DELETE) args+=(-X DELETE "${BASE_API}/${endpoint}") ;;
    esac

    curl "${args[@]}"
}

api_call_with_status() {
    local method="$1"
    local endpoint="$2"
    local data="${3:-}"

    local args=(-s -w "\n%{http_code}" -u ":${PAT}" -H "Content-Type: application/json")

    case "$method" in
        GET)    args+=("${BASE_API}/${endpoint}") ;;
        POST)   args+=(-X POST --data "$data" "${BASE_API}/${endpoint}") ;;
        PATCH)  args+=(-X PATCH --data "$data" "${BASE_API}/${endpoint}") ;;
        PUT)    args+=(-X PUT --data "$data" "${BASE_API}/${endpoint}") ;;
    esac

    curl "${args[@]}"
}

# ============================================================
# Commands
# ============================================================

case "${1:-}" in
    create-pr)
        # Create PR: create-pr SOURCE_BRANCH TARGET_BRANCH "Title" "Description"
        source_branch="$2"
        target_branch="$3"
        title="$4"
        description="${5:-}"

        json=$(jq -n \
            --arg src "refs/heads/$source_branch" \
            --arg tgt "refs/heads/$target_branch" \
            --arg title "$title" \
            --arg desc "$description" \
            '{
                sourceRefName: $src,
                targetRefName: $tgt,
                title: $title,
                description: $desc
            }')

        response=$(api_call_with_status POST "pullrequests?api-version=7.0" "$json")
        http_code=$(echo "$response" | tail -1)
        body=$(echo "$response" | sed '$d')

        if [[ "$http_code" =~ ^2 ]]; then
            pr_id=$(echo "$body" | jq -r '.pullRequestId')
            echo "$body" | jq -r '"PR #\(.pullRequestId): \(.title)"'
            echo "Status: $(echo "$body" | jq -r '.status')"
            echo "URL: ${WEB_URL}/pullrequest/${pr_id}"
        else
            echo "Failed to create PR (HTTP $http_code)" >&2
            echo "$body" | jq -r '.message // .' 2>/dev/null >&2
            exit 1
        fi
        ;;

    list-prs)
        # List PRs: list-prs [active|completed|abandoned|all]
        status="${2:-active}"

        if [[ "$status" == "all" ]]; then
            endpoint="pullrequests?api-version=7.0"
        else
            endpoint="pullrequests?searchCriteria.status=${status}&api-version=7.0"
        fi

        api_call GET "$endpoint" | \
            jq -r '.value[] | "#\(.pullRequestId) | \(.title) | \(.status) | \(.createdBy.displayName) | \(.targetRefName | gsub("refs/heads/"; ""))"'
        ;;

    my-prs)
        # List my open PRs
        api_call GET "pullrequests?searchCriteria.status=active&api-version=7.0" | \
            jq -r --arg me "$(git config user.email)" \
            '.value[] | select(.createdBy.uniqueName == $me) | "#\(.pullRequestId) | \(.title) | \(.status) | \(.targetRefName | gsub("refs/heads/"; ""))"'
        ;;

    get-pr)
        # Get PR details: get-pr PR_ID
        pr_id="$2"

        body=$(api_call GET "pullrequests/${pr_id}?api-version=7.0")
        echo "$body" | jq -r '
            "PR #\(.pullRequestId): \(.title)",
            "Status: \(.status)",
            "Merge: \(.mergeStatus // "unknown")",
            "Source: \(.sourceRefName | gsub("refs/heads/"; ""))",
            "Target: \(.targetRefName | gsub("refs/heads/"; ""))",
            "Author: \(.createdBy.displayName)",
            "Created: \(.creationDate)",
            "",
            "Description:",
            (.description // "(none)")
        '
        echo ""
        echo "URL: ${WEB_URL}/pullrequest/${pr_id}"

        # Show reviewers if any
        reviewers=$(echo "$body" | jq -r '.reviewers[]? | "  \(.displayName): \(if .vote > 0 then "Approved" elif .vote < 0 then "Rejected" else "No vote" end)"')
        if [[ -n "$reviewers" ]]; then
            echo ""
            echo "Reviewers:"
            echo "$reviewers"
        fi
        ;;

    update-pr)
        # Update PR: update-pr PR_ID "New Title" ["New Description"]
        pr_id="$2"
        new_title="$3"
        new_description="${4:-}"

        if [[ -n "$new_description" ]]; then
            json=$(jq -n --arg t "$new_title" --arg d "$new_description" '{title: $t, description: $d}')
        else
            json=$(jq -n --arg t "$new_title" '{title: $t}')
        fi

        response=$(api_call_with_status PATCH "pullrequests/${pr_id}?api-version=7.0" "$json")
        http_code=$(echo "$response" | tail -1)
        body=$(echo "$response" | sed '$d')

        if [[ "$http_code" =~ ^2 ]]; then
            echo "PR #${pr_id} updated"
            echo "URL: ${WEB_URL}/pullrequest/${pr_id}"
        else
            echo "Failed to update PR (HTTP $http_code)" >&2
            echo "$body" | jq -r '.message // .' 2>/dev/null >&2
            exit 1
        fi
        ;;

    add-reviewers)
        # Add reviewers: add-reviewers PR_ID email1 [email2 ...]
        pr_id="$2"
        shift 2

        for email in "$@"; do
            # Look up identity by email
            json=$(jq -n --arg id "$email" '{id: $id, isRequired: true}')

            response=$(api_call_with_status PUT "pullrequests/${pr_id}/reviewers/${email}?api-version=7.0" "$json")
            http_code=$(echo "$response" | tail -1)

            if [[ "$http_code" =~ ^2 ]]; then
                echo "Added reviewer: $email"
            else
                echo "Failed to add reviewer $email (HTTP $http_code)" >&2
            fi
        done
        echo "URL: ${WEB_URL}/pullrequest/${pr_id}"
        ;;

    complete-pr)
        # Complete (merge) PR: complete-pr PR_ID [squash|merge|rebase]
        pr_id="$2"
        merge_strategy="${3:-squash}"

        # Get current PR to find last merge source commit
        pr_data=$(api_call GET "pullrequests/${pr_id}?api-version=7.0")
        last_commit=$(echo "$pr_data" | jq -r '.lastMergeSourceCommit.commitId')
        creator_id=$(echo "$pr_data" | jq -r '.createdBy.id')

        case "$merge_strategy" in
            squash)  merge_type=2 ;;
            merge)   merge_type=1 ;;
            rebase)  merge_type=3 ;;
            *)       echo "Unknown merge strategy: $merge_strategy (use: squash, merge, rebase)" >&2; exit 1 ;;
        esac

        json=$(jq -n \
            --arg commit "$last_commit" \
            --arg creator "$creator_id" \
            --argjson type "$merge_type" \
            '{
                status: "completed",
                lastMergeSourceCommit: {commitId: $commit},
                completionOptions: {
                    mergeStrategy: (if $type == 1 then "noFastForward" elif $type == 2 then "squash" else "rebaseMerge" end),
                    deleteSourceBranch: true
                }
            }')

        response=$(api_call_with_status PATCH "pullrequests/${pr_id}?api-version=7.0" "$json")
        http_code=$(echo "$response" | tail -1)
        body=$(echo "$response" | sed '$d')

        if [[ "$http_code" =~ ^2 ]]; then
            echo "PR #${pr_id} completed ($merge_strategy merge)"
            echo "URL: ${WEB_URL}/pullrequest/${pr_id}"
        else
            echo "Failed to complete PR (HTTP $http_code)" >&2
            echo "$body" | jq -r '.message // .' 2>/dev/null >&2
            exit 1
        fi
        ;;

    abandon-pr)
        # Abandon PR: abandon-pr PR_ID
        pr_id="$2"

        json='{"status":"abandoned"}'

        response=$(api_call_with_status PATCH "pullrequests/${pr_id}?api-version=7.0" "$json")
        http_code=$(echo "$response" | tail -1)
        body=$(echo "$response" | sed '$d')

        if [[ "$http_code" =~ ^2 ]]; then
            echo "PR #${pr_id} abandoned"
            echo "URL: ${WEB_URL}/pullrequest/${pr_id}"
        else
            echo "Failed to abandon PR (HTTP $http_code)" >&2
            echo "$body" | jq -r '.message // .' 2>/dev/null >&2
            exit 1
        fi
        ;;

    *)
        cat << 'EOF'
Usage: azure-devops-rest-api.sh <command> [args]

Requires: git repo with Azure DevOps remote, git credential manager configured.
Auth and repo info are auto-detected from git remote origin.

PR Operations:
  create-pr <source> <target> <title> [description]
                             Create a pull request
                             Example: create-pr feature/WEMC-123 master_6.0.x "fix: [WEMC-123] Fix bug" "Description"

  list-prs [status]          List pull requests (default: active)
                             Status: active, completed, abandoned, all
                             Example: list-prs active

  my-prs                     List my open pull requests

  get-pr <pr-id>             Get PR details, status, reviewers
                             Example: get-pr 916

  update-pr <pr-id> <title> [description]
                             Update PR title and description
                             Example: update-pr 916 "New title" "New description"

  add-reviewers <pr-id> <email> [email2 ...]
                             Add reviewers to a PR
                             Example: add-reviewers 916 user@example.com

  complete-pr <pr-id> [strategy]
                             Complete (merge) a PR
                             Strategy: squash (default), merge, rebase
                             Example: complete-pr 916 squash

  abandon-pr <pr-id>         Abandon a PR
                             Example: abandon-pr 916
EOF
        ;;
esac
