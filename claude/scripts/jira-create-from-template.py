#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Create/update Jira issues from YAML templates with proper ADF formatting.

Usage:
    jira-create-from-template.py <issue-key> <template-path>

Environment variables:
    ATLASSIAN_EMAIL      - Your Atlassian email
    ATLASSIAN_API_TOKEN  - Your Atlassian API token
    JIRA_URL             - Your Jira URL (e.g., https://your-company.atlassian.net)

Examples:
    export ATLASSIAN_EMAIL="user@example.com"
    export ATLASSIAN_API_TOKEN="your-token-here"
    export JIRA_URL="https://your-company.atlassian.net"

    python jira-create-from-template.py PROJ-123 ~/.claude/jira-templates/epics/my-epic.yaml
    python jira-create-from-template.py PROJ-456 ~/.claude/jira-templates/stories/my-story.yaml
"""

import json
import os
import sys
import io
from typing import List, Dict, Any
import yaml

try:
    import requests
except ImportError:
    print("Error: requests library not installed")
    print("Install with: pip install requests pyyaml")
    sys.exit(1)

# Set UTF-8 encoding for Windows console
if sys.platform == 'win32':
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')

# Configuration from environment
JIRA_USER = os.getenv("ATLASSIAN_EMAIL")
JIRA_TOKEN = os.getenv("ATLASSIAN_API_TOKEN")
JIRA_URL = os.getenv("JIRA_URL")


def heading(level: int, text: str, emoji: str = None) -> Dict[str, Any]:
    """Create ADF heading node."""
    content = []
    if emoji:
        emoji_map = {
            "📰": {"shortName": ":newspaper:", "id": "1f4f0", "text": "📰"},
            "🔥": {"shortName": ":fire:", "id": "1f525", "text": "🔥"},
            "🏅": {"shortName": ":medal:", "id": "1f3c5", "text": "🏅"},
            "🎯": {"shortName": ":dart:", "id": "1f3af", "text": "🎯"},
            "📈": {"shortName": ":chart_with_upwards_trend:", "id": "1f4c8", "text": "📈"},
            "💪": {"shortName": ":muscle:", "id": "1f4aa", "text": "💪"},
            "⛔": {"shortName": ":no_entry:", "id": "26d4", "text": "⛔"},
            "📚": {"shortName": ":books:", "id": "1f4da", "text": "📚"},
            "✅": {"shortName": ":white_check_mark:", "id": "2705", "text": "✅"},
            "💡": {"shortName": ":bulb:", "id": "1f4a1", "text": "💡"},
            "🚫": {"shortName": ":no_entry_sign:", "id": "1f6ab", "text": "🚫"},
            "📋": {"shortName": ":clipboard:", "id": "1f4cb", "text": "📋"},
            "🛠️": {"shortName": ":hammer_and_wrench:", "id": "1f6e0", "text": "🛠️"},
            "🗒️": {"shortName": ":spiral_notepad:", "id": "1f5d2", "text": "🗒️"},
            "🐛": {"shortName": ":bug:", "id": "1f41b", "text": "🐛"},
            "🕵️": {"shortName": ":detective:", "id": "1f575", "text": "🕵️"},
            "📽️": {"shortName": ":film_projector:", "id": "1f4fd", "text": "📽️"},
        }
        emoji_data = emoji_map.get(emoji, {"shortName": ":question:", "id": "2753", "text": emoji})
        content.append({"type": "emoji", "attrs": emoji_data})
        content.append({"type": "text", "text": " "})

    content.append({"type": "text", "text": text})

    return {
        "type": "heading",
        "attrs": {"level": level},
        "content": content
    }


def paragraph(text: str, marks: List[str] = None, color: str = None) -> Dict[str, Any]:
    """Create ADF paragraph node."""
    text_node = {"type": "text", "text": text}

    mark_list = []
    if marks:
        mark_list.extend([{"type": mark} for mark in marks])
    if color:
        mark_list.append({"type": "textColor", "attrs": {"color": color}})

    if mark_list:
        text_node["marks"] = mark_list

    return {
        "type": "paragraph",
        "content": [text_node]
    }


def bullet_list(items: List[str], color: str = None) -> Dict[str, Any]:
    """Create ADF bullet list node."""
    list_items = []
    for item in items:
        list_items.append({
            "type": "listItem",
            "content": [paragraph(item, color=color)]
        })

    return {
        "type": "bulletList",
        "content": list_items
    }


def code_block(language: str, code: str) -> Dict[str, Any]:
    """Create ADF code block node."""
    return {
        "type": "codeBlock",
        "attrs": {"language": language},
        "content": [
            {
                "type": "text",
                "text": code.strip()
            }
        ]
    }


def numbered_table(items: List[str]) -> Dict[str, Any]:
    """Create ADF numbered table with single column (for acceptance criteria)."""
    rows = []
    for item in items:
        rows.append({
            "type": "tableRow",
            "content": [
                {
                    "type": "tableCell",
                    "content": [paragraph(item)]
                }
            ]
        })

    return {
        "type": "table",
        "attrs": {"isNumberColumnEnabled": True, "layout": "default"},
        "content": rows
    }


def epic_from_yaml(data: Dict[str, Any]) -> Dict[str, Any]:
    """Convert YAML epic template to ADF."""

    # Build Impact cell content
    impact_content = []
    if data['prioritization']['impact'].get('bullets'):
        impact_content.append(bullet_list(data['prioritization']['impact']['bullets']))
    if data['prioritization']['impact'].get('reach'):
        impact_content.append(paragraph(data['prioritization']['impact']['reach']))

    # Build Effort cell content
    effort_content = []
    if data['prioritization']['effort'].get('bullets'):
        effort_content.append(bullet_list(data['prioritization']['effort']['bullets']))

    # Build Required Outcomes table
    outcome_rows = []
    for item in data['required_outcomes']:
        outcome_rows.append({
            "type": "tableRow",
            "content": [
                {
                    "type": "tableCell",
                    "content": [paragraph(item['outcome'], marks=["strong"])]
                },
                {
                    "type": "tableCell",
                    "content": [paragraph(item['notes'])]
                }
            ]
        })

    content = [
        heading(2, "Context", "📰"),
        paragraph(data['context'].strip()),

        heading(2, "Prioritization Information", "🏅"),
        {
            "type": "table",
            "attrs": {"isNumberColumnEnabled": False, "layout": "default"},
            "content": [
                {
                    "type": "tableRow",
                    "content": [
                        {
                            "type": "tableHeader",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [
                                        {"type": "emoji", "attrs": {"shortName": ":chart_with_upwards_trend:", "id": "1f4c8", "text": "📈"}},
                                        {"type": "text", "text": " "},
                                        {"type": "text", "text": "Impact", "marks": [{"type": "strong"}]}
                                    ]
                                }
                            ]
                        },
                        {
                            "type": "tableCell",
                            "content": impact_content
                        }
                    ]
                },
                {
                    "type": "tableRow",
                    "content": [
                        {
                            "type": "tableHeader",
                            "content": [
                                {
                                    "type": "paragraph",
                                    "content": [
                                        {"type": "emoji", "attrs": {"shortName": ":muscle:", "id": "1f4aa", "text": "💪"}},
                                        {"type": "text", "text": " "},
                                        {"type": "text", "text": "Effort", "marks": [{"type": "strong"}]}
                                    ]
                                }
                            ]
                        },
                        {
                            "type": "tableCell",
                            "content": effort_content
                        }
                    ]
                }
            ]
        },

        heading(2, "Required Outcomes", "🎯"),
        {
            "type": "table",
            "attrs": {"isNumberColumnEnabled": True, "layout": "default"},
            "content": [
                {
                    "type": "tableRow",
                    "content": [
                        {
                            "type": "tableHeader",
                            "content": [paragraph("Required Outcome", marks=["strong"])]
                        },
                        {
                            "type": "tableHeader",
                            "content": [paragraph("Notes", marks=["strong"])]
                        }
                    ]
                },
                *outcome_rows
            ]
        },

        heading(2, "Specifically Not In Scope", "🚫"),
        bullet_list(data['not_in_scope']),

        heading(2, "Additional Information & Resources", "📚"),
        bullet_list(data['resources'])
    ]

    return {
        "type": "doc",
        "version": 1,
        "content": content
    }


def story_from_yaml(data: Dict[str, Any]) -> Dict[str, Any]:
    """Convert YAML story template to ADF."""
    content = [
        heading(2, "Context", "📰"),
        paragraph(data['context'].strip(), color="#97a0af"),

        heading(2, "Impact", "📈"),
        paragraph(data['impact'].strip(), color="#97a0af"),

        heading(2, "Acceptance Criteria", "📋"),
        numbered_table(data['acceptance_criteria']),

        heading(2, "Implementation/Technical Details", "🛠️"),
    ]

    # Add implementation details
    for section in data['implementation']:
        if section.get('text'):
            content.append(paragraph(section['text'], color="#97a0af"))
        if section.get('bullets'):
            content.append(bullet_list(section['bullets'], color="#97a0af"))
        if section.get('code_blocks'):
            for code_block_data in section['code_blocks']:
                content.append(code_block(
                    code_block_data.get('language', 'text'),
                    code_block_data.get('content', '')
                ))

    content.extend([
        heading(2, "Specifically Not In Scope", "⛔"),
        bullet_list(data['not_in_scope'], color="#97a0af")
    ])

    # Only add resources section if not empty
    if data.get('resources') and len(data['resources']) > 0:
        content.extend([
            heading(2, "Additional Information & Resources", "📚"),
            bullet_list(data['resources'], color="#97a0af")
        ])

    return {
        "type": "doc",
        "version": 1,
        "content": content
    }


def bug_from_yaml(data: Dict[str, Any]) -> Dict[str, Any]:
    """Convert YAML bug template to ADF."""
    content = [
        heading(2, "Summary"),
        paragraph(data['summary'].strip()),

        heading(2, "Steps To Reproduce", "🗒️"),
        {
            "type": "orderedList",
            "attrs": {"order": 1},
            "content": [
                {
                    "type": "listItem",
                    "content": [paragraph(item)]
                }
                for item in data['steps_to_reproduce']
            ]
        },

        heading(2, "Actual Result", "🐛"),
        bullet_list(data['actual_result']),

        heading(2, "Expected Result", "🎯"),
        bullet_list(data['expected_result']),
    ]

    # Optional video/screenshots
    if data.get('video_recording') and data['video_recording'].strip():
        content.extend([
            heading(2, "Video Recording Demonstration", "📽️"),
            paragraph(data['video_recording'].strip())
        ])

    content.extend([
        heading(2, "Impact", "📈"),
        bullet_list(data['impact']),

        {"type": "rule"},  # Horizontal divider

        paragraph("<Below section is to be filled out by the team fixing the defect>", marks=["em"]),

        heading(2, "Cause of Bug", "🕵️"),
        paragraph(data.get('cause_of_bug', '…').strip()),

        heading(2, "Solution/Acceptance Criteria", "💡"),
        {
            "type": "table",
            "attrs": {"isNumberColumnEnabled": True, "layout": "default"},
            "content": [
                {
                    "type": "tableRow",
                    "content": [
                        {
                            "type": "tableCell",
                            "content": [paragraph(item)]
                        }
                    ]
                }
                for item in data['solution']
            ]
        },

        heading(2, "Additional Information", "📚"),
        paragraph(data.get('additional_info', '…').strip())
    ])

    return {
        "type": "doc",
        "version": 1,
        "content": content
    }


def load_template(template_path: str) -> Dict[str, Any]:
    """Load YAML template file."""
    with open(template_path, 'r', encoding='utf-8') as f:
        return yaml.safe_load(f)


def update_issue(issue_key: str, description: Dict[str, Any], parent_key: str = None, value_stream: str = None) -> None:
    """Update Jira issue description with ADF content."""
    url = f"{JIRA_URL}/rest/api/3/issue/{issue_key}"

    payload = {
        "fields": {
            "description": description
        }
    }

    # Add parent if specified
    if parent_key:
        payload["fields"]["parent"] = {"key": parent_key}

    # Add Value Stream if specified (custom field - may vary by Jira instance)
    if value_stream:
        # Note: Custom field ID may differ in your Jira instance
        # Find your field ID via: GET /rest/api/3/field
        payload["fields"]["customfield_10344"] = {"value": value_stream}

    response = requests.put(
        url,
        auth=(JIRA_USER, JIRA_TOKEN),
        headers={"Content-Type": "application/json"},
        json=payload
    )

    if response.status_code == 204:
        print(f"[OK] Updated {issue_key}")
        if parent_key:
            print(f"  Parent: {parent_key}")
        if value_stream:
            print(f"  Value Stream: {value_stream}")
        print(f"  URL: {JIRA_URL}/browse/{issue_key}")
    else:
        print(f"[ERROR] Failed to update {issue_key}")
        print(f"  Status: {response.status_code}")
        print(f"  Response: {response.text}")


def main():
    if len(sys.argv) < 3:
        print(__doc__)
        sys.exit(1)

    # Validate configuration
    missing = []
    if not JIRA_USER:
        missing.append("ATLASSIAN_EMAIL")
    if not JIRA_TOKEN:
        missing.append("ATLASSIAN_API_TOKEN")
    if not JIRA_URL:
        missing.append("JIRA_URL")

    if missing:
        print(f"Error: Missing required environment variables: {', '.join(missing)}")
        print("\nSet them with:")
        print('  export ATLASSIAN_EMAIL="your-email@example.com"')
        print('  export ATLASSIAN_API_TOKEN="your-api-token"')
        print('  export JIRA_URL="https://your-company.atlassian.net"')
        sys.exit(1)

    issue_key = sys.argv[1]
    template_path = os.path.expanduser(sys.argv[2])

    if not os.path.exists(template_path):
        print(f"[ERROR] Template not found: {template_path}")
        sys.exit(1)

    print(f"Loading template: {template_path}")
    data = load_template(template_path)

    print(f"Converting to ADF format...")

    # Detect type from path or data
    template_path_normalized = template_path.replace('\\', '/')
    if '/epics/' in template_path_normalized or data.get('type') == 'epic':
        description = epic_from_yaml(data)
    elif '/stories/' in template_path_normalized or data.get('type') == 'story':
        description = story_from_yaml(data)
    elif '/bugs/' in template_path_normalized or data.get('type') == 'bug':
        description = bug_from_yaml(data)
    else:
        print("[ERROR] Could not determine issue type (epic/story/bug)")
        print(f"  Path: {template_path_normalized}")
        print(f"  Type: {data.get('type')}")
        sys.exit(1)

    print(f"Updating {issue_key}...")

    # Extract parent key and value stream if present
    parent_key = data.get('parent')
    value_stream = data.get('value_stream')
    update_issue(issue_key, description, parent_key, value_stream)

    print("\nDone! Check the issue in Jira to verify formatting.")


if __name__ == "__main__":
    main()
