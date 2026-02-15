#!/bin/bash
# Confluence REST API wrapper
# Requires environment variables: ATLASSIAN_EMAIL, ATLASSIAN_API_TOKEN

# Source shared Atlassian validation
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "${SCRIPT_DIR}/atlassian-common.sh"

# Set service-specific variables
CONF_USER="${ATLASSIAN_EMAIL}"
CONF_TOKEN="${ATLASSIAN_API_TOKEN}"
# CONFLUENCE_URL loaded from config/env by atlassian-common.sh

case "$1" in
    get)
        # Get page by ID
        curl -s -u "${CONF_USER}:${CONF_TOKEN}" \
            "${CONF_URL}/rest/api/content/$2?expand=body.storage,version,space" | \
            jq -r '"ID: " + .id, "Title: " + .title, "Space: " + .space.name, "Version: " + (.version.number|tostring), "", "Content:", .body.storage.value'
        ;;

    search)
        # Search pages by title
        query="$2"
        space="${3:-}"

        if [ -n "$space" ]; then
            cql="title~\"$query\" AND space=$space"
        else
            cql="title~\"$query\""
        fi

        curl -s -u "${CONF_USER}:${CONF_TOKEN}" \
            "${CONF_URL}/rest/api/content/search?cql=$(echo "$cql" | jq -sRr @uri)" | \
            jq -r '.results[]? | "[\(.id)] \(.title) | Space: \(.space.key)"'
        ;;

    create)
        # Create page: create SPACE "TITLE" "CONTENT" [PARENT-ID]
        space="$2"
        title="$3"
        content="$4"
        parent_id="${5:-}"

        json=$(jq -n \
            --arg space "$space" \
            --arg title "$title" \
            --arg content "$content" \
            '{type: "page", title: $title, space: {key: $space}, body: {storage: {value: $content, representation: "storage"}}}')

        if [ -n "$parent_id" ]; then
            json=$(echo "$json" | jq --arg pid "$parent_id" '.ancestors = [{id: $pid}]')
        fi

        curl -s -u "${CONF_USER}:${CONF_TOKEN}" \
            -X POST \
            -H "Content-Type: application/json" \
            --data "$json" \
            "${CONF_URL}/rest/api/content" | \
            jq -r '"✓ Page created", "ID: " + .id, "Title: " + .title, "URL: ${CONFLUENCE_URL}/spaces/" + .space.key + "/pages/" + .id'
        ;;

    update)
        # Update page: update PAGE-ID "CONTENT" VERSION
        page_id="$2"
        content="$3"
        version="$4"

        # Get current page title
        title=$(curl -s -u "${CONF_USER}:${CONF_TOKEN}" \
            "${CONF_URL}/rest/api/content/$page_id" | jq -r '.title')

        json=$(jq -n \
            --arg title "$title" \
            --arg content "$content" \
            --argjson version "$version" \
            '{type: "page", title: $title, body: {storage: {value: $content, representation: "storage"}}, version: {number: $version}}')

        curl -s -u "${CONF_USER}:${CONF_TOKEN}" \
            -X PUT \
            -H "Content-Type: application/json" \
            --data "$json" \
            "${CONF_URL}/rest/api/content/$page_id" | \
            jq -r '"✓ Page updated", "ID: " + .id, "Version: " + (.version.number|tostring)'
        ;;

    my-pages)
        # Get your recent pages
        curl -s -u "${CONF_USER}:${CONF_TOKEN}" \
            "${CONF_URL}/rest/api/content?type=page&limit=25&expand=space,version" | \
            jq -r '.results[] | select(.history.createdBy.email == "'"$CONF_USER"'") | "[\(.id)] \(.title) | \(.space.name) | v\(.version.number)"'
        ;;

    spaces)
        # List spaces
        curl -s -u "${CONF_USER}:${CONF_TOKEN}" \
            "${CONF_URL}/rest/api/space?limit=50" | \
            jq -r '.results[]? | "[\(.key)] \(.name) | Type: \(.type)"'
        ;;

    create-from-md)
        # Create page from markdown file: create-from-md SPACE "TITLE" FILE_PATH [PARENT-ID]
        space="$2"
        title="$3"
        md_file="$4"
        parent_id="${5:-}"

        if [ ! -f "$md_file" ]; then
            echo "Error: File not found: $md_file"
            exit 1
        fi

        # Convert markdown to Confluence HTML
        # Using pandoc if available, otherwise basic conversion
        if command -v pandoc &> /dev/null; then
            html=$(pandoc -f markdown -t html "$md_file" | sed 's/^//')
        else
            # Basic markdown to HTML conversion using sed
            html=$(cat "$md_file" | \
                sed 's/^# \(.*\)/<h1>\1<\/h1>/' | \
                sed 's/^## \(.*\)/<h2>\1<\/h2>/' | \
                sed 's/^### \(.*\)/<h3>\1<\/h3>/' | \
                sed 's/^#### \(.*\)/<h4>\1<\/h4>/' | \
                sed 's/\*\*\([^*]*\)\*\*/<strong>\1<\/strong>/g' | \
                sed 's/\*\([^*]*\)\*/<em>\1<\/em>/g' | \
                sed 's/`\([^`]*\)`/<code>\1<\/code>/g' | \
                sed 's/^\- \(.*\)/<li>\1<\/li>/' | \
                sed 's/^\* \(.*\)/<li>\1<\/li>/' | \
                sed 's/^\([0-9]\+\)\. \(.*\)/<li>\2<\/li>/' | \
                sed 's/\[\([^]]*\)\](\([^)]*\))/<a href="\2">\1<\/a>/g' | \
                sed 's/^$/<\/p><p>/' | \
                sed '1s/^/<p>/' | \
                sed '$s/$/<\/p>/' | \
                tr '\n' ' ')
        fi

        # Call create with the converted HTML
        if [ -n "$parent_id" ]; then
            $0 create "$space" "$title" "$html" "$parent_id"
        else
            $0 create "$space" "$title" "$html"
        fi
        ;;

    *)
        echo "Usage: $0 {get|search|create|create-from-md|update|my-pages|spaces} [args]"
        echo ""
        echo "Commands:"
        echo "  get PAGE-ID                              - Get page content"
        echo "  search 'QUERY' [SPACE]                   - Search pages"
        echo "  create SPACE 'TITLE' 'CONTENT' [PID]     - Create page with HTML"
        echo "  create-from-md SPACE 'TITLE' FILE [PID]  - Create page from markdown file"
        echo "  update PAGE-ID 'CONTENT' VERSION         - Update page"
        echo "  my-pages                                 - Your recent pages"
        echo "  spaces                                   - List spaces"
        echo ""
        echo "Examples:"
        echo "  $0 get 5153062922"
        echo "  $0 search 'SegmentExplorer'"
        echo "  $0 search 'Architecture' ENG"
        echo "  $0 create ~828448473 'My Page' '<h1>Content</h1>'"
        echo "  $0 create-from-md ~828448473 'Analysis' docs/analysis.md"
        echo "  $0 my-pages"
        ;;
esac
