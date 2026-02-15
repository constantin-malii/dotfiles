---
name: confluence
description: Search Confluence, read pages, create documentation using REST API
---

# Confluence Operations (Generic)

**Trigger**: When the user asks to search Confluence, read Confluence pages, create documentation, find docs, or any Confluence-related query.

**Goal**: Help search, read, and create Confluence documentation using the REST API wrapper.

## How to Help

When the user mentions Confluence operations:
1. Parse their intent (search, read page, create page, list spaces)
2. Run the appropriate wrapper command
3. Format and present results clearly
4. For page creation, use proper HTML/XHTML format

## Available Commands

### Search Pages
```bash
bash ~/.claude/scripts/confluence-rest-api.sh search "<QUERY>" [SPACE-KEY]
```

### Get Page Content
```bash
bash ~/.claude/scripts/confluence-rest-api.sh get <PAGE-ID>
```

### Create Page
```bash
bash ~/.claude/scripts/confluence-rest-api.sh create <SPACE> "<TITLE>" "<CONTENT>" [PARENT-ID]
```

### List Spaces
```bash
bash ~/.claude/scripts/confluence-rest-api.sh spaces
```

### Get User's Recent Pages
```bash
bash ~/.claude/scripts/confluence-rest-api.sh my-pages
```

## Common User Requests

**"Search for [topic]"** → Run `search` command

**"Find docs about X"** → Run `search "X"`

**"Read page [ID]"** → Run `get [ID]`

**"Show my Confluence pages"** → Run `my-pages`

**"Create a page about X"** → Create page with HTML content

**"Document [topic]"** → Create comprehensive documentation page

## Example Interactions

```
User: Search Confluence for SegmentExplorer

You: [Run: bash ~/.claude/scripts/confluence-rest-api.sh search "SegmentExplorer"]
     Present results:

     Found 3 pages:
     - [5153062922] SegmentExplorer Python Service
     - [5154209798] SegmentExplorer Architecture

User: Read page 5153062922

You: [Run: bash ~/.claude/scripts/confluence-rest-api.sh get 5153062922]
     Show: Title, Space, Version, and formatted content

User: Create a page documenting PL-9137

You: [Get Jira ticket details first]
     [Create page with proper HTML:]

     Title: "PL-9137: ML job lifecycle tracing"
     Content:
     <h1>Overview</h1>
     <p>Summary from Jira ticket...</p>
     <h2>Implementation</h2>
     <p>Details...</p>
     <h2>Related Links</h2>
     <p><a href="...">PL-9137</a></p>
```

## Content Format

Always use valid HTML/XHTML:
```html
<h1>Main Title</h1>
<h2>Section</h2>
<p>Paragraph with <strong>bold</strong> and <em>italic</em>.</p>
<ul>
  <li>Bullet point</li>
</ul>
<ol>
  <li>Numbered item</li>
</ol>
<a href="url">Link text</a>
```

## Output Formatting

- Show page titles and IDs
- Include direct links to pages
- Format content readably
- For search results, list most relevant first
- Suggest follow-up actions (read, edit, create related pages)

## Advantages

- ✅ No size limits
- ✅ Create large documents in one call
- ✅ Full HTML formatting support
- ✅ No re-authentication needed
