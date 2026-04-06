#!/usr/bin/env python3
"""
Upload large markdown files to Confluence using REST API.
Handles files of any size by reading from disk instead of command-line args.

Usage:
    confluence-upload-large.py SPACE_KEY TITLE MD_FILE_PATH [PARENT_ID]

Environment variables:
    CONFLUENCE_EMAIL      - Your Atlassian email
    CONFLUENCE_API_TOKEN  - Your Atlassian API token
    CONFLUENCE_URL        - Your Confluence URL (e.g., https://your-company.atlassian.net/wiki)

Example:
    export CONFLUENCE_EMAIL="user@example.com"
    export CONFLUENCE_API_TOKEN="your-token-here"
    export CONFLUENCE_URL="https://your-company.atlassian.net/wiki"
    python3 confluence-upload-large.py "SPACE" "My Page" "doc.md"
"""

import os
import sys
import json
import requests

try:
    from md2cf.confluence_renderer import ConfluenceRenderer
    import mistune
except ImportError:
    print("Error: 'md2cf' or 'mistune' module not found. Install with: pip install md2cf mistune")
    sys.exit(1)

# Configuration from environment
CONFLUENCE_EMAIL = os.getenv("CONFLUENCE_EMAIL")
CONFLUENCE_API_TOKEN = os.getenv("CONFLUENCE_API_TOKEN")
CONFLUENCE_URL = os.getenv("CONFLUENCE_URL")

def convert_md_to_html(md_content):
    """Convert markdown to Confluence storage format"""
    renderer = ConfluenceRenderer(use_xhtml=True)
    confluence_mistune = mistune.Markdown(renderer=renderer)
    return confluence_mistune(md_content)

def create_confluence_page(space_key, title, html_content, parent_id=None):
    """Create a Confluence page"""
    url = f"{CONFLUENCE_URL}/rest/api/content"

    headers = {
        "Accept": "application/json",
        "Content-Type": "application/json"
    }

    payload = {
        "type": "page",
        "title": title,
        "space": {"key": space_key},
        "body": {
            "storage": {
                "value": html_content,
                "representation": "storage"
            }
        }
    }

    if parent_id:
        payload["ancestors"] = [{"id": parent_id}]

    response = requests.post(
        url,
        headers=headers,
        json=payload,
        auth=(CONFLUENCE_EMAIL, CONFLUENCE_API_TOKEN)
    )

    if response.status_code == 200:
        result = response.json()
        page_url = f"{CONFLUENCE_URL}{result['_links']['webui']}"
        print("Page created successfully")
        print(f"ID: {result['id']}")
        print(f"Title: {result['title']}")
        print(f"URL: {page_url}")
        return result
    else:
        print(f"Error creating page: {response.status_code}")
        print(response.text)
        sys.exit(1)

def main():
    if len(sys.argv) < 4:
        print(__doc__)
        sys.exit(1)

    space_key = sys.argv[1]
    title = sys.argv[2]
    md_file_path = sys.argv[3]
    parent_id = sys.argv[4] if len(sys.argv) > 4 else None

    # Validate configuration
    missing = []
    if not CONFLUENCE_EMAIL:
        missing.append("CONFLUENCE_EMAIL")
    if not CONFLUENCE_API_TOKEN:
        missing.append("CONFLUENCE_API_TOKEN")
    if not CONFLUENCE_URL:
        missing.append("CONFLUENCE_URL")

    if missing:
        print(f"Error: Missing required environment variables: {', '.join(missing)}")
        print("\nSet them with:")
        print('  export CONFLUENCE_EMAIL="your-email@example.com"')
        print('  export CONFLUENCE_API_TOKEN="your-api-token"')
        print('  export CONFLUENCE_URL="https://your-company.atlassian.net/wiki"')
        sys.exit(1)

    # Read markdown file
    try:
        with open(md_file_path, 'r', encoding='utf-8') as f:
            md_content = f.read()
    except FileNotFoundError:
        print(f"Error: File not found: {md_file_path}")
        sys.exit(1)

    # Check file size
    file_size_mb = len(md_content) / (1024 * 1024)
    print(f"File size: {file_size_mb:.2f} MB")

    # Convert to HTML
    print("Converting markdown to HTML...")
    html_content = convert_md_to_html(md_content)

    # Create page
    print(f"Creating page in space {space_key}...")
    create_confluence_page(space_key, title, html_content, parent_id)

if __name__ == "__main__":
    main()
