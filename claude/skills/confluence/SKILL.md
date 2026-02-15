---
name: confluence
description: Create technical docs, search Confluence, use documentation templates
---

# Confluence Operations

**Trigger**: When the user asks to create technical docs, search Confluence, document tickets, or create project documentation.

**Goal**: Help create and search Confluence documentation following standard templates and conventions.

## How to Help

### When user asks to search docs:
```bash
bash ~/.claude/scripts/confluence-rest-api.sh search "<QUERY>"
```

### When user wants to document a ticket:
**Recommended workflow (Markdown):**
1. Get ticket details from Jira first
2. Write markdown file to appropriate `docs/` directory
3. Create Confluence page from markdown:
```bash
bash ~/.claude/scripts/confluence-rest-api.sh create-from-md "SPACE-KEY" "Page Title" docs/TICKET-Analysis.md
```

**Alternative (HTML):**
1. Get ticket details from Jira first
2. Create Confluence page with HTML content
3. Include Jira link and use appropriate template

### When user wants to create technical documentation:
**Recommended workflow:**
1. Write markdown documentation file
2. Create page from markdown using `create-from-md`

**Alternative:**
1. Choose appropriate template
2. Create page in team space
3. Include proper sections, code examples, links

## Documentation Templates

### Spike Documentation
```html
<h1>Spike: {Topic Name}</h1>

<h2>Problem Statement</h2>
<p>{Description of problem or question}</p>

<h2>Investigation</h2>
<p>{What was researched, tested, analyzed}</p>

<h2>Findings</h2>
<ul>
  <li>Key finding 1</li>
  <li>Key finding 2</li>
</ul>

<h2>Proposed Solution</h2>
<p>{Recommended approach}</p>

<h2>Trade-offs</h2>
<table>
  <tbody>
    <tr><th>Option</th><th>Pros</th><th>Cons</th></tr>
    <tr><td>Option A</td><td>Benefits</td><td>Drawbacks</td></tr>
  </tbody>
</table>

<h2>Related Jira</h2>
<p><a href="{jira-url}/browse/TICKET-####">TICKET-####</a></p>
```

### Feature Implementation Guide
```html
<h1>Feature: {Feature Name}</h1>

<h2>User Story</h2>
<p>As a {role}, I want {goal} so that {benefit}.</p>

<h2>Requirements</h2>
<ul>
  <li>Requirement 1</li>
  <li>Requirement 2</li>
</ul>

<h2>Implementation Details</h2>
<h3>API Changes</h3>
<p>{New endpoints or modifications}</p>

<h3>Database Changes</h3>
<p>{Schema updates or migrations}</p>

<h3>Code Structure</h3>
<ac:structured-macro ac:name="code">
  <ac:parameter ac:name="language">python</ac:parameter>
  <ac:plain-text-body><![CDATA[
# Code example
def example():
    pass
]]></ac:plain-text-body>
</ac:structured-macro>

<h2>Testing</h2>
<ul>
  <li>Unit tests</li>
  <li>Integration tests</li>
  <li>Manual test scenarios</li>
</ul>

<h2>Deployment</h2>
<p>{Deployment steps and considerations}</p>

<h2>Related Jira</h2>
<p><a href="{jira-url}/browse/TICKET-####">TICKET-####</a></p>
```

### Incident Postmortem
```html
<h1>Incident: {Brief Description}</h1>

<h2>Summary</h2>
<table>
  <tbody>
    <tr><th>Date</th><td>{Date}</td></tr>
    <tr><th>Duration</th><td>{Duration}</td></tr>
    <tr><th>Impact</th><td>{What was affected}</td></tr>
    <tr><th>Root Cause</th><td>{Brief cause}</td></tr>
  </tbody>
</table>

<h2>Timeline</h2>
<ul>
  <li>{Time} - Detection</li>
  <li>{Time} - Initial response</li>
  <li>{Time} - Root cause identified</li>
  <li>{Time} - Fix deployed</li>
  <li>{Time} - Resolved</li>
</ul>

<h2>Root Cause Analysis</h2>
<p>{Detailed explanation of what happened and why}</p>

<h2>Resolution</h2>
<p>{What was done to fix it}</p>

<h2>Action Items</h2>
<table>
  <tbody>
    <tr><th>Action</th><th>Owner</th><th>Status</th></tr>
    <tr><td>Prevent recurrence</td><td>{Name}</td><td>{Status}</td></tr>
    <tr><td>Improve monitoring</td><td>{Name}</td><td>{Status}</td></tr>
  </tbody>
</table>

<h2>Related Jira</h2>
<ul>
  <li><a href="{jira-url}/browse/TICKET-####">TICKET-####</a> - Prevent recurrence</li>
</ul>
```

### Technical Design Document
```html
<h1>Design: {System/Feature Name}</h1>

<h2>Overview</h2>
<p>{High-level description}</p>

<h2>Goals</h2>
<ul>
  <li>Goal 1</li>
  <li>Goal 2</li>
</ul>

<h2>Non-Goals</h2>
<ul>
  <li>What this does NOT cover</li>
</ul>

<h2>Architecture</h2>
<p>{System design, components, interactions}</p>

<h2>API Design</h2>
<ac:structured-macro ac:name="code">
  <ac:parameter ac:name="language">json</ac:parameter>
  <ac:plain-text-body><![CDATA[
{
  "endpoint": "/api/v1/resource",
  "method": "POST",
  "request": {},
  "response": {}
}
]]></ac:plain-text-body>
</ac:structured-macro>

<h2>Data Model</h2>
<p>{Database schema or data structures}</p>

<h2>Security Considerations</h2>
<ul>
  <li>Authentication</li>
  <li>Authorization</li>
  <li>Data encryption</li>
</ul>

<h2>Performance</h2>
<p>{Expected load, scaling considerations}</p>

<h2>Alternatives Considered</h2>
<table>
  <tbody>
    <tr><th>Alternative</th><th>Pros</th><th>Cons</th><th>Decision</th></tr>
    <tr><td>Option A</td><td>...</td><td>...</td><td>Not selected</td></tr>
  </tbody>
</table>

<h2>Open Questions</h2>
<ul>
  <li>Question 1</li>
  <li>Question 2</li>
</ul>
```

### API Documentation
```html
<h1>API: {Service Name}</h1>

<h2>Base URL</h2>
<p><code>{base-url}</code></p>

<h2>Authentication</h2>
<p>{Auth method - Bearer token, API key, etc.}</p>

<h2>Endpoints</h2>

<h3>GET /resource</h3>
<p>{Description}</p>

<h4>Request</h4>
<ac:structured-macro ac:name="code">
  <ac:parameter ac:name="language">bash</ac:parameter>
  <ac:plain-text-body><![CDATA[
curl -X GET {base-url}/resource \
  -H "Authorization: Bearer {token}"
]]></ac:plain-text-body>
</ac:structured-macro>

<h4>Response</h4>
<ac:structured-macro ac:name="code">
  <ac:parameter ac:name="language">json</ac:parameter>
  <ac:plain-text-body><![CDATA[
{
  "data": [],
  "status": "success"
}
]]></ac:plain-text-body>
</ac:structured-macro>

<h4>Error Codes</h4>
<table>
  <tbody>
    <tr><th>Code</th><th>Description</th></tr>
    <tr><td>400</td><td>Bad Request</td></tr>
    <tr><td>401</td><td>Unauthorized</td></tr>
    <tr><td>404</td><td>Not Found</td></tr>
  </tbody>
</table>
```

## Common Operations

### Create Page from Markdown
```bash
bash ~/.claude/scripts/confluence-rest-api.sh create-from-md "SPACE" "Title" file.md
```

### Search
```bash
bash ~/.claude/scripts/confluence-rest-api.sh search "keyword"
bash ~/.claude/scripts/confluence-rest-api.sh search "keyword" SPACE
```

### Get Page
```bash
bash ~/.claude/scripts/confluence-rest-api.sh get PAGE-ID
```

### Create Page with HTML
```bash
bash ~/.claude/scripts/confluence-rest-api.sh create "SPACE" "Title" "<html content>"
```

## Best Practices

1. **Always link to Jira**: Include `[TICKET-####](jira-url)` in documentation
2. **Use proper templates**: Choose template based on doc type
3. **Code examples**: Use Confluence code blocks with syntax highlighting
4. **Keep it updated**: Update docs when implementation changes
5. **Version control**: Keep markdown sources in git, sync to Confluence

## Example Interactions

```
User: Document the spike for database migration

You: [Get spike details if from Jira ticket]

     I'll create a spike document. Let me write it to a markdown file first:

     [Write to docs/TICKET-spike-db-migration.md using spike template]

     Now creating Confluence page:
     bash ~/.claude/scripts/confluence-rest-api.sh create-from-md "SPACE" "Spike: Database Migration" docs/TICKET-spike-db-migration.md

     ✓ Page created

User: Create API documentation for the new endpoint

You: [Write API docs using template]

     I'll create comprehensive API documentation:

     [Write to docs/api-new-endpoint.md]

     Creating Confluence page:
     bash ~/.claude/scripts/confluence-rest-api.sh create-from-md "SPACE" "API: New Endpoint" docs/api-new-endpoint.md
```

## Tips

- **Markdown first**: Write docs in markdown, commit to git, then sync to Confluence
- **Template customization**: Adapt templates to your team's needs
- **Space organization**: Use team spaces for shared docs, personal space for drafts
- **Links**: Always provide Jira ticket links in related sections
- **Code formatting**: Use proper language tags in code blocks
