#!/bin/bash
# Jira REST API wrapper - Full CRUD operations
# Requires environment variables: ATLASSIAN_EMAIL, ATLASSIAN_API_TOKEN

# Source shared Atlassian validation
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/atlassian-common.sh"

# Set service-specific variables
JIRA_USER="${ATLASSIAN_EMAIL}"
JIRA_TOKEN="${ATLASSIAN_API_TOKEN}"
# JIRA_URL loaded from config/env by atlassian-common.sh

case "$1" in
    get)
        # Get issue details: get PROJ-1234
        curl -s -u "${JIRA_USER}:${JIRA_TOKEN}" \
            "${JIRA_URL}/rest/api/3/issue/$2" | \
            jq -r '
                "Key: " + .key,
                "Summary: " + .fields.summary,
                "Type: " + .fields.issuetype.name,
                "Status: " + .fields.status.name,
                "Priority: " + (.fields.priority.name // "None"),
                "Assignee: " + (.fields.assignee.displayName // "Unassigned"),
                "Reporter: " + (.fields.reporter.displayName // "Unknown"),
                "",
                "Description:",
                if .fields.description == null then
                    "(none)"
                elif (.fields.description | type) == "object" then
                    (.fields.description | [.. | .text? // empty] | join(" "))
                else
                    (.fields.description | tostring)
                end
            '
        ;;

    search)
        # Search with JQL: search "project=PL AND status=Open" [max]
        curl -s -u "${JIRA_USER}:${JIRA_TOKEN}" \
            -X POST -H "Content-Type: application/json" \
            --data "{\"jql\":\"$2\",\"maxResults\":${3:-10},\"fields\":[\"summary\",\"status\",\"assignee\"]}" \
            "${JIRA_URL}/rest/api/3/search/jql" | \
            jq -r '.issues[]? | "[\(.key)] \(.fields.summary) | \(.fields.status.name) | \(.fields.assignee.displayName // "Unassigned")"'
        ;;

    mine)
        # Get your open issues
        $0 search "assignee = currentUser() AND resolution = Unresolved ORDER BY updated DESC" 10
        ;;

    create)
        # Create issue: create PROJECT "Summary" "Description" [ISSUE_TYPE]
        project="$2"
        summary="$3"
        description="$4"
        issue_type="${5:-Task}"

        json=$(jq -n \
            --arg project "$project" \
            --arg summary "$summary" \
            --arg description "$description" \
            --arg type "$issue_type" \
            '{
                fields: {
                    project: {key: $project},
                    summary: $summary,
                    description: {
                        type: "doc",
                        version: 1,
                        content: [{
                            type: "paragraph",
                            content: [{type: "text", text: $description}]
                        }]
                    },
                    issuetype: {name: $type}
                }
            }')

        curl -s -u "${JIRA_USER}:${JIRA_TOKEN}" \
            -X POST \
            -H "Content-Type: application/json" \
            --data "$json" \
            "${JIRA_URL}/rest/api/3/issue" | \
            jq -r '"✓ Issue created", "Key: " + .key, "URL: ${JIRA_URL}/browse/" + .key'
        ;;

    update)
        # Update issue field: update PL-1234 summary "New summary"
        # Or: update PL-1234 description "New description"
        issue_key="$2"
        field="$3"
        value="$4"

        case "$field" in
            summary)
                json=$(jq -n --arg val "$value" '{fields: {summary: $val}}')
                ;;
            description)
                json=$(jq -n --arg val "$value" '{
                    fields: {
                        description: {
                            type: "doc",
                            version: 1,
                            content: [{
                                type: "paragraph",
                                content: [{type: "text", text: $val}]
                            }]
                        }
                    }
                }')
                ;;
            *)
                echo "Error: Field must be 'summary' or 'description'"
                exit 1
                ;;
        esac

        curl -s -u "${JIRA_USER}:${JIRA_TOKEN}" \
            -X PUT \
            -H "Content-Type: application/json" \
            --data "$json" \
            "${JIRA_URL}/rest/api/3/issue/$issue_key"

        if [ $? -eq 0 ]; then
            echo "✓ Issue $issue_key updated"
            echo "URL: ${JIRA_URL}/browse/$issue_key"
        else
            echo "✗ Failed to update issue"
        fi
        ;;

    comment)
        # Add comment: comment PL-1234 "Comment text"
        issue_key="$2"
        comment_text="$3"

        json=$(jq -n --arg text "$comment_text" '{
            body: {
                type: "doc",
                version: 1,
                content: [{
                    type: "paragraph",
                    content: [{type: "text", text: $text}]
                }]
            }
        }')

        curl -s -u "${JIRA_USER}:${JIRA_TOKEN}" \
            -X POST \
            -H "Content-Type: application/json" \
            --data "$json" \
            "${JIRA_URL}/rest/api/3/issue/$issue_key/comment" | \
            jq -r '"✓ Comment added to " + .self'

        echo "URL: ${JIRA_URL}/browse/$issue_key"
        ;;

    transition)
        # Change status: transition PL-1234 "Done"
        # Or list available transitions: transition PL-1234
        issue_key="$2"
        status_name="$3"

        if [ -z "$status_name" ]; then
            # List available transitions
            echo "Available transitions for $issue_key:"
            curl -s -u "${JIRA_USER}:${JIRA_TOKEN}" \
                "${JIRA_URL}/rest/api/3/issue/$issue_key/transitions" | \
                jq -r '.transitions[] | "  \(.id): \(.name)"'
        else
            # Get transition ID for status name
            transition_id=$(curl -s -u "${JIRA_USER}:${JIRA_TOKEN}" \
                "${JIRA_URL}/rest/api/3/issue/$issue_key/transitions" | \
                jq -r --arg name "$status_name" '.transitions[] | select(.name == $name) | .id')

            if [ -z "$transition_id" ]; then
                echo "✗ Transition '$status_name' not found. Use '$0 transition $issue_key' to list available transitions."
                exit 1
            fi

            json=$(jq -n --arg id "$transition_id" '{transition: {id: $id}}')

            curl -s -u "${JIRA_USER}:${JIRA_TOKEN}" \
                -X POST \
                -H "Content-Type: application/json" \
                --data "$json" \
                "${JIRA_URL}/rest/api/3/issue/$issue_key/transitions"

            if [ $? -eq 0 ]; then
                echo "✓ Issue $issue_key transitioned to '$status_name'"
                echo "URL: ${JIRA_URL}/browse/$issue_key"
            else
                echo "✗ Failed to transition issue"
            fi
        fi
        ;;

    assign)
        # Assign issue: assign PL-1234 "user@example.com"
        # Or assign to me: assign PL-1234 me
        issue_key="$2"
        assignee="$3"

        if [ "$assignee" = "me" ]; then
            # Assign to current user
            json='{"accountId": null}'  # null means assign to self
        else
            # Get account ID from email
            account_id=$(curl -s -u "${JIRA_USER}:${JIRA_TOKEN}" \
                "${JIRA_URL}/rest/api/3/user/search?query=$assignee" | \
                jq -r '.[0].accountId')

            if [ -z "$account_id" ] || [ "$account_id" = "null" ]; then
                echo "✗ User not found: $assignee"
                exit 1
            fi

            json=$(jq -n --arg id "$account_id" '{accountId: $id}')
        fi

        curl -s -u "${JIRA_USER}:${JIRA_TOKEN}" \
            -X PUT \
            -H "Content-Type: application/json" \
            --data "$json" \
            "${JIRA_URL}/rest/api/3/issue/$issue_key/assignee"

        if [ $? -eq 0 ]; then
            echo "✓ Issue $issue_key assigned"
            echo "URL: ${JIRA_URL}/browse/$issue_key"
        else
            echo "✗ Failed to assign issue"
        fi
        ;;

    labels)
        # Add labels: labels PL-1234 add "label1,label2"
        # Remove labels: labels PL-1234 remove "label1,label2"
        issue_key="$2"
        action="$3"
        labels="$4"

        # Convert comma-separated string to JSON array
        IFS=',' read -ra LABEL_ARRAY <<< "$labels"
        label_json=$(printf '%s\n' "${LABEL_ARRAY[@]}" | jq -R . | jq -s .)

        case "$action" in
            add)
                json=$(echo "$label_json" | jq '{update: {labels: [.[] | {add: .}]}}')
                ;;
            remove)
                json=$(echo "$label_json" | jq '{update: {labels: [.[] | {remove: .}]}}')
                ;;
            *)
                echo "Error: Action must be 'add' or 'remove'"
                exit 1
                ;;
        esac

        curl -s -u "${JIRA_USER}:${JIRA_TOKEN}" \
            -X PUT \
            -H "Content-Type: application/json" \
            --data "$json" \
            "${JIRA_URL}/rest/api/3/issue/$issue_key"

        if [ $? -eq 0 ]; then
            echo "✓ Labels ${action}ed on $issue_key"
            echo "URL: ${JIRA_URL}/browse/$issue_key"
        else
            echo "✗ Failed to ${action} labels"
        fi
        ;;

    link)
        # Link issues: link PL-1234 "relates to" PL-5678
        # Common link types: "relates to", "blocks", "is blocked by", "duplicates"
        from_issue="$2"
        link_type="$3"
        to_issue="$4"

        json=$(jq -n \
            --arg type "$link_type" \
            --arg from "$from_issue" \
            --arg to "$to_issue" \
            '{
                type: {name: $type},
                inwardIssue: {key: $from},
                outwardIssue: {key: $to}
            }')

        curl -s -u "${JIRA_USER}:${JIRA_TOKEN}" \
            -X POST \
            -H "Content-Type: application/json" \
            --data "$json" \
            "${JIRA_URL}/rest/api/3/issueLink" | \
            jq -r '"✓ Issues linked"'

        echo "From: ${JIRA_URL}/browse/$from_issue"
        echo "To:   ${JIRA_URL}/browse/$to_issue"
        ;;

    *)
        cat << 'EOF'
Usage: jira-rest-api.sh <command> [args]

READ Operations:
  get <issue-key>              Get issue details
                               Example: get PL-1234

  search <jql> [max]           Search with JQL (default max: 10)
                               Example: search "project=PL AND status=Open" 20

  mine                         Get your open issues

CREATE/UPDATE Operations:
  create <project> <summary> <description> [type]
                               Create new issue (default type: Task)
                               Example: create PL "Fix bug" "Bug description" Bug

  update <issue-key> <field> <value>
                               Update issue (field: summary or description)
                               Example: update PL-1234 summary "New summary"

  comment <issue-key> <text>   Add comment
                               Example: comment PL-1234 "Work in progress"

  transition <issue-key> [status]
                               Change status or list available transitions
                               Example: transition PL-1234 "Done"
                               Example: transition PL-1234 (lists options)

  assign <issue-key> <email|me>
                               Assign issue
                               Example: assign PL-1234 me
                               Example: assign PL-1234 user@example.com

  labels <issue-key> <add|remove> <labels>
                               Add or remove labels (comma-separated)
                               Example: labels PL-1234 add "bug,urgent"

  link <from-issue> <type> <to-issue>
                               Link two issues
                               Example: link PL-1234 "relates to" PL-5678
                               Types: "relates to", "blocks", "is blocked by", "duplicates"

Common JQL Examples:
  project = PL AND status = Open
  assignee = currentUser() AND resolution = Unresolved
  project = PL AND created >= -7d
  status changed to Done during (startOfWeek(), endOfWeek())
EOF
        ;;
esac
