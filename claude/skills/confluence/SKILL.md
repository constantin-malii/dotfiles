---
name: confluence
description: Create and search Confluence documentation using standard templates. Use when the user asks to create technical docs, search Confluence, document a ticket or spike, write a postmortem, create API docs, or publish project documentation.
argument-hint: [command] [args...]
allowed-tools: Bash Read Write Grep Glob
---

# Confluence Operations

If arguments are provided, interpret them as a command:
- `/confluence search "keyword"` → run `bash ~/.claude/scripts/confluence-rest-api.sh search "keyword"`
- `/confluence get PAGE-ID` → run `bash ~/.claude/scripts/confluence-rest-api.sh get PAGE-ID`

When invoked with arguments: `bash ~/.claude/scripts/confluence-rest-api.sh $ARGUMENTS`

## How to Help

### When user asks to search docs:
```bash
bash ~/.claude/scripts/confluence-rest-api.sh search "<QUERY>"
```

### When user wants to document a ticket:
1. Get ticket details from Jira first
2. Write markdown file to appropriate `docs/` directory
3. Create Confluence page from markdown:
```bash
bash ~/.claude/scripts/confluence-rest-api.sh create-from-md "SPACE-KEY" "Page Title" docs/TICKET-Analysis.md
```

### When user wants to create technical documentation:
1. Write markdown documentation file
2. Create page from markdown using `create-from-md`

## Documentation Templates

### Spike Documentation
```html
<h1>Spike: {Topic Name}</h1>
<h2>Problem Statement</h2>
<p>{Description of problem or question}</p>
<h2>Investigation</h2>
<p>{What was researched, tested, analyzed}</p>
<h2>Findings</h2>
<ul><li>Key finding 1</li><li>Key finding 2</li></ul>
<h2>Proposed Solution</h2>
<p>{Recommended approach}</p>
<h2>Trade-offs</h2>
<table><tbody>
  <tr><th>Option</th><th>Pros</th><th>Cons</th></tr>
  <tr><td>Option A</td><td>Benefits</td><td>Drawbacks</td></tr>
</tbody></table>
<h2>Related Jira</h2>
<p><a href="{jira-url}/browse/TICKET-####">TICKET-####</a></p>
```

### Feature Implementation Guide
```html
<h1>Feature: {Feature Name}</h1>
<h2>User Story</h2>
<p>As a {role}, I want {goal} so that {benefit}.</p>
<h2>Requirements</h2>
<ul><li>Requirement 1</li></ul>
<h2>Implementation Details</h2>
<h3>API Changes</h3><p>{New endpoints or modifications}</p>
<h3>Database Changes</h3><p>{Schema updates or migrations}</p>
<h2>Testing</h2>
<ul><li>Unit tests</li><li>Integration tests</li></ul>
<h2>Related Jira</h2>
<p><a href="{jira-url}/browse/TICKET-####">TICKET-####</a></p>
```

### Incident Postmortem
```html
<h1>Incident: {Brief Description}</h1>
<h2>Summary</h2>
<table><tbody>
  <tr><th>Date</th><td>{Date}</td></tr>
  <tr><th>Duration</th><td>{Duration}</td></tr>
  <tr><th>Impact</th><td>{What was affected}</td></tr>
  <tr><th>Root Cause</th><td>{Brief cause}</td></tr>
</tbody></table>
<h2>Timeline</h2>
<ul>
  <li>{Time} - Detection</li>
  <li>{Time} - Root cause identified</li>
  <li>{Time} - Resolved</li>
</ul>
<h2>Root Cause Analysis</h2>
<p>{Detailed explanation}</p>
<h2>Action Items</h2>
<table><tbody>
  <tr><th>Action</th><th>Owner</th><th>Status</th></tr>
  <tr><td>Prevent recurrence</td><td>{Name}</td><td>{Status}</td></tr>
</tbody></table>
```

### Technical Design Document
```html
<h1>Design: {System/Feature Name}</h1>
<h2>Overview</h2><p>{High-level description}</p>
<h2>Goals</h2><ul><li>Goal 1</li></ul>
<h2>Non-Goals</h2><ul><li>What this does NOT cover</li></ul>
<h2>Architecture</h2><p>{System design, components, interactions}</p>
<h2>Alternatives Considered</h2>
<table><tbody>
  <tr><th>Alternative</th><th>Pros</th><th>Cons</th><th>Decision</th></tr>
</tbody></table>
```

## Common Operations

```bash
bash ~/.claude/scripts/confluence-rest-api.sh search "keyword"
bash ~/.claude/scripts/confluence-rest-api.sh search "keyword" SPACE
bash ~/.claude/scripts/confluence-rest-api.sh get PAGE-ID
bash ~/.claude/scripts/confluence-rest-api.sh create "SPACE" "Title" "<html content>"
bash ~/.claude/scripts/confluence-rest-api.sh create-from-md "SPACE" "Title" file.md
bash ~/.claude/scripts/confluence-rest-api.sh my-pages
bash ~/.claude/scripts/confluence-rest-api.sh spaces
```

## Best Practices

1. **Always link to Jira**: Include `[TICKET-####](jira-url)` in documentation
2. **Markdown first**: Write docs in markdown, commit to git, then sync to Confluence
3. **Use proper templates**: Choose template based on doc type
4. **Keep it updated**: Update docs when implementation changes

## Example Interactions

```
User: Document the spike for database migration
You: [Get spike details from Jira, write markdown using spike template, create Confluence page]

User: Create API documentation for the new endpoint
You: [Write API docs using template, create Confluence page from markdown]
```
