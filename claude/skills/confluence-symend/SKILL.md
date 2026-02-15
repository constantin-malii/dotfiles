---
name: confluence-symend
description: Document Symend work, create technical docs, search Confluence with team templates
---

# Confluence Operations (Symend)

**Trigger**: When the user asks to document Symend work, create technical docs, search Symend Confluence, create spike documentation, or document PL tickets in Confluence.

**Goal**: Help create and search Symend-specific Confluence documentation following team templates and conventions. Personal space: `~828448473`

## How to Help

### When user asks to search Symend docs:
```bash
bash ~/.claude/scripts/confluence-rest-api.sh search "<QUERY>"
```
Focus on SegmentExplorer, CureInsights, and other Symend services.

### When user wants to document a ticket:
**Streamlined flow:**
1. Get ticket details from Jira first
2. Write markdown file to appropriate `docs/` directory:
   - Use current working directory context
   - Common patterns: `docs/`, `csharp/docs/`, `python/docs/`
   - Example: If working in segmentexplorer/csharp, write to `docs/PL-XXXX-Analysis.md`
3. Create Confluence page directly from markdown:
```bash
# Use relative path from current directory OR absolute path
bash ~/.claude/scripts/confluence-rest-api.sh create-from-md "~828448473" "Title" docs/PL-XXXX-Analysis.md
bash ~/.claude/scripts/confluence-rest-api.sh create-from-md "~828448473" "Title" /absolute/path/to/file.md
```

**Alternative (HTML):**
1. Get ticket details from Jira first
2. Create Confluence page with HTML content
3. Include Jira link
4. Use appropriate template (spike, feature, incident, etc.)

### When user wants to create technical documentation:
**Streamlined flow:**
1. Write markdown documentation file
2. Create page from markdown file using `create-from-md` command

**Alternative (HTML):**
1. Choose appropriate template based on doc type
2. Create page in personal space (`~828448473`) or team space
3. Include proper sections, code examples, links

## Symend Documentation Templates

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
<p><a href="https://symend.atlassian.net/browse/PL-XXXX">PL-XXXX</a></p>
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
<pre>{SQL or migration details}</pre>

<h2>Testing Strategy</h2>
<ul>
  <li>Unit tests for service layer</li>
  <li>Integration tests for API</li>
</ul>

<h2>Related Jira</h2>
<p><a href="https://symend.atlassian.net/browse/PL-XXXX">PL-XXXX</a></p>
```

### Post-Incident Analysis
```html
<h1>Incident: {Brief Description}</h1>

<h2>Summary</h2>
<ul>
  <li><strong>Date:</strong> YYYY-MM-DD</li>
  <li><strong>Duration:</strong> X hours</li>
  <li><strong>Impact:</strong> {Description}</li>
  <li><strong>Severity:</strong> Critical/High/Medium/Low</li>
</ul>

<h2>Timeline</h2>
<table>
  <tbody>
    <tr><th>Time</th><th>Event</th></tr>
    <tr><td>10:00 AM</td><td>Issue detected</td></tr>
    <tr><td>10:15 AM</td><td>Investigation started</td></tr>
  </tbody>
</table>

<h2>Root Cause</h2>
<p>{Technical explanation}</p>

<h2>Resolution</h2>
<p>{How issue was resolved}</p>

<h2>Action Items</h2>
<ul>
  <li><a href="https://symend.atlassian.net/browse/PL-XXXX">PL-XXXX</a> - Prevent recurrence</li>
</ul>
```

## Example Interactions

```
User: Document PL-9137 in Confluence

You: [Get PL-9137 from Jira]
     [Create Confluence page:]

     Title: "PL-9137: ML job lifecycle tracing"
     Space: ~828448473
     Content: (structured with summary, implementation, links)

     ✓ Page created: https://symend.atlassian.net/wiki/spaces/~828448473/pages/XXXXX

User: Create a spike doc for trace propagation

You: [Use spike template]
     Title: "Spike: Saga Trace Propagation Analysis"
     Sections: Problem, Investigation, Findings, Solution, Trade-offs

User: Search for SegmentExplorer architecture docs

You: [Run: bash ~/.claude/scripts/confluence-rest-api.sh search "SegmentExplorer architecture"]
     List results with IDs and links

User: Create incident report for yesterday's outage

You: [Use incident template]
     Ask for: Date, duration, impact, timeline events
     Create structured incident page
```

## Service-Specific Documentation

When documenting Symend services:
- **SegmentExplorer**: Include API endpoints, state machines, CureInsights details
- **CureInsights**: Document BDA/RDA models, training/inference workflows
- **Data Flow**: Show how data moves between services
- **Architecture**: Include diagrams, component interactions, external dependencies

## Best Practices

1. **Always link to Jira**: Include `[PL-####](https://symend.atlassian.net/browse/PL-####)`
2. **Link to GitHub**: Reference PRs and commits
3. **Use templates**: Follow team documentation patterns
4. **Personal space first**: Draft in `~828448473`, move to team space when ready
5. **Version control**: Update docs when implementations change
6. **Code examples**: Use `<pre>` tags for code blocks
7. **Context-aware paths**: Determine correct docs/ location based on current working directory and service structure

## Common Commands

### For Normal-Sized Files (< 20KB markdown)

```bash
# Search
bash ~/.claude/scripts/confluence-rest-api.sh search "SegmentExplorer"
bash ~/.claude/scripts/confluence-rest-api.sh search "CureInsights"

# Create page from markdown file (RECOMMENDED)
# Use relative path (context-aware) or absolute path
bash ~/.claude/scripts/confluence-rest-api.sh create-from-md "~828448473" "PL-XXXX Analysis" docs/PL-XXXX-Analysis.md
bash ~/.claude/scripts/confluence-rest-api.sh create-from-md "~828448473" "Analysis" /full/path/to/file.md

# Create page with HTML (for templates)
bash ~/.claude/scripts/confluence-rest-api.sh create "~828448473" "Title" "<h1>Content</h1>"

# Create child page under parent
bash ~/.claude/scripts/confluence-rest-api.sh create-from-md "~828448473" "Child" docs/file.md PARENT-ID

# Get your recent pages
bash ~/.claude/scripts/confluence-rest-api.sh my-pages
```

### For Large Files (> 20KB markdown) ⚠️

The bash script hits **command-line argument limits** with large files (>20KB markdown becomes >100KB HTML).

**Symptom**: Error "Argument list too long" or "jq: Argument list too long"

**Solution**: Use Python script for large files:

```bash
# One-time setup (if not already done)
pip install requests markdown

# Set credentials (bash script already has these)
export CONFLUENCE_EMAIL="your.email@company.com"
export CONFLUENCE_API_TOKEN="<from bash script>"

# Upload large file
python3 ~/.claude/scripts/confluence-upload-large.py \
  "~828448473" \
  "Page Title" \
  docs/large-document.md

# With parent page
python3 ~/.claude/scripts/confluence-upload-large.py \
  "~828448473" \
  "Page Title" \
  docs/large-document.md \
  PARENT-PAGE-ID
```

**Why Python for large files?**
- Bash passes file content as command-line arguments (OS limit ~128KB-2MB)
- Python reads file into memory (no argument limit)
- Better markdown conversion (uses proper `markdown` library)

**When to use each:**
- **Bash script** (default): Files < 20KB markdown, quick operations
- **Python script**: Files > 20KB, complex markdown (tables, code blocks)

## Troubleshooting

### "Argument list too long" Error

**Cause**: Bash script hits OS command-line argument length limit with large files.

**Solution**: Use Python script for large files (see "For Large Files" section above).

**Prevention**:
- Keep markdown docs < 20KB for bash script
- Split very large documents into multiple pages
- Use Python script for comprehensive technical documents

### Page Already Exists Error

**Cause**: A page with the same title already exists in the space.

**Solution**: Use a different title or update the existing page instead.

```bash
# Search for existing page first
bash ~/.claude/scripts/confluence-rest-api.sh search "Page Title" "~828448473"

# Use unique title
bash ~/.claude/scripts/confluence-rest-api.sh create-from-md "~828448473" "Page Title v2" docs/file.md
```

## Output Formatting

- Include full URLs to created pages
- Show page IDs for easy reference
- Format results clearly with links
- Suggest related documentation or next steps
- Follow Symend conventions in all content
