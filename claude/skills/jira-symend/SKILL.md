---
name: jira-symend
description: Symend PL project Jira workflows, tickets, branches, PRs with conventions
---

# Jira Operations (Symend PL Project)

**Trigger**: When the user asks about Jira issues in the Symend repo, wants to check PL tickets, start work on a ticket, create a PR for a ticket, or any PL project Jira operations.

**Goal**: Help with Symend PL project Jira workflows including checking tickets, starting work, creating branches, and preparing PRs with proper conventions.

## Symend Conventions

- **Project**: PL
- **Branch Format**: `feature/PL-{number}_{description}` (lowercase with underscores)
- **Commit Format**: `{type}: [PL-{number}] {Description}`
- **PR Format**: `{type}: [PL-{number}] {Description}`
- **Jira URL**: https://symend.atlassian.net/browse/PL-{number}

## How to Help

### When user asks to see their issues:
```bash
bash ~/.claude/scripts/jira-rest-api.sh mine
```
Format as numbered list with links to Jira.

### When user asks about specific ticket (e.g., "What's PL-9137?"):
```bash
bash ~/.claude/scripts/jira-rest-api.sh get PL-9137
```
Show key details: Summary, Status, Assignee, Description.

### When user wants to start work on a ticket:
1. Get ticket details
2. Suggest branch name: `feature/PL-{number}_{descriptive_name}`
3. Show git commands:
   ```bash
   git checkout -b feature/PL-9137_description
   ```
4. Remind about commit format: `feat: [PL-9137] Description`

### When user wants to create PR for a ticket:
1. Get ticket details
2. Suggest PR title: `{type}: [PL-{number}] {Summary}`
3. Generate PR body with Jira link:
   ```markdown
   ## Summary
   {Brief description}

   ## Related issues
   - [PL-####](https://symend.atlassian.net/browse/PL-####)

   ## Checklist
   - [ ] Tests pass
   - [ ] Code reviewed
   ```

## Create and Update Operations

### Create a new issue:
```bash
bash ~/.claude/scripts/jira-rest-api.sh create PL "Bug fix for login" "User cannot login when..." Bug
```

### Update issue:
```bash
# Update summary
bash ~/.claude/scripts/jira-rest-api.sh update PL-1234 summary "New summary text"

# Update description
bash ~/.claude/scripts/jira-rest-api.sh update PL-1234 description "New description"
```

### Add comment:
```bash
bash ~/.claude/scripts/jira-rest-api.sh comment PL-1234 "Work in progress, blocked by PL-5678"
```

### Change status (transition):
```bash
# List available transitions
bash ~/.claude/scripts/jira-rest-api.sh transition PL-1234

# Move to specific status
bash ~/.claude/scripts/jira-rest-api.sh transition PL-1234 "In Progress"
bash ~/.claude/scripts/jira-rest-api.sh transition PL-1234 "Done"
```

### Assign issue:
```bash
# Assign to yourself
bash ~/.claude/scripts/jira-rest-api.sh assign PL-1234 me

# Assign to another user
bash ~/.claude/scripts/jira-rest-api.sh assign PL-1234 user@example.com
```

### Manage labels:
```bash
# Add labels
bash ~/.claude/scripts/jira-rest-api.sh labels PL-1234 add "bug,urgent"

# Remove labels
bash ~/.claude/scripts/jira-rest-api.sh labels PL-1234 remove "needs-review"
```

### Link issues:
```bash
bash ~/.claude/scripts/jira-rest-api.sh link PL-1234 "blocks" PL-5678
bash ~/.claude/scripts/jira-rest-api.sh link PL-1234 "relates to" PL-9999
```

## Common Search Patterns

### Service-Specific Searches
```bash
# SegmentExplorer tickets
bash ~/.claude/scripts/jira-rest-api.sh search "project = PL AND summary ~ 'SegmentExplorer'" 20

# CureInsights tickets
bash ~/.claude/scripts/jira-rest-api.sh search "project = PL AND (summary ~ 'CureInsights' OR description ~ 'CureInsights')" 20

# Recent updates
bash ~/.claude/scripts/jira-rest-api.sh search "project = PL AND updated >= -7d ORDER BY updated DESC" 20
```

## Example Interactions

```
User: Show my PL issues

You: [Run mine command]
     Present as:

     You have 10 open PL issues:
     1. [PL-9205](link) SPIKE | Technical design | Defining Requirements
     2. [PL-9106](link) DA | ML Model Registry fixes | Defining Requirements
     ...

User: I want to work on PL-9137

You: [Get ticket details]
     Present:

     **PL-9137: ML job lifecycle tracing**
     Status: Defining Requirements

     Suggested branch name:
     `feature/PL-9137_ml_job_trace_propagation`

     Commands:
     ```bash
     git checkout -b feature/PL-9137_ml_job_trace_propagation
     ```

     When committing, use:
     `feat: [PL-9137] Add trace continuation for sagas`

User: Create PR for PL-9137

You: [Get ticket]
     Generate PR template:

     **Title:** feat: [PL-9137] Add trace continuation for MassTransit sagas

     **Body:**
     ## Summary
     Implement trace continuation for saga workflows.

     ## Related issues
     - [PL-9137](https://symend.atlassian.net/browse/PL-9137)

User: Find CureInsights tickets

You: [Run search with CureInsights filter]
     List results with links
```

## Useful JQL Queries

```jql
# My active work
project = PL AND assignee = currentUser() AND resolution = Unresolved

# Ready for dev
project = PL AND status = "Ready for Dev" AND assignee is EMPTY

# Current sprint
project = PL AND sprint in openSprints()

# Blocked tickets
project = PL AND status = Blocked

# Recently completed
project = PL AND status = Done AND resolved >= -7d ORDER BY resolved DESC
```

## Template System for Epics and Stories

For creating properly formatted epics with stories, use the template system:

### Create Epic with Stories
```bash
# 1. Copy and edit epic template
cp ~/.claude/jira-templates/epic-template.yaml ~/.claude/jira-templates/epics/my-epic.yaml
# Edit YAML: Set type, value_stream, context, prioritization, outcomes, etc.

# 2. Update Jira epic
python ~/.claude/scripts/jira-create-from-template.py PL-#### ~/.claude/jira-templates/epics/my-epic.yaml

# 3. Copy and edit story template
cp ~/.claude/jira-templates/story-template.yaml ~/.claude/jira-templates/stories/my-story.yaml
# Edit YAML: Set parent: PL-#### (epic), context, impact, acceptance_criteria, etc.

# 4. Update Jira story
python ~/.claude/scripts/jira-create-from-template.py PL-#### ~/.claude/jira-templates/stories/my-story.yaml

# 5. Create story dependencies
bash ~/.claude/scripts/create-issue-link.sh PL-9337 PL-9336  # 9337 blocked by 9336
```

### Template Features
- **Proper formatting**: Gray text, numbered tables, code blocks
- **Parent-child relationships**: Stories automatically become children of epics
- **Value Stream**: Automatically set via YAML field
- **Resources**: Link Confluence docs in epic resources section

### Important Rules
- Stories `parent` field creates child relationship (not link)
- Resources section: Only external links (Confluence, docs), never Jira references
- Dependencies: Use `create-issue-link.sh`, not text in resources
- Value Stream: Use `value_stream: "Insights & Analysis"` for analytics work

See `~/.claude/jira-templates/README.md` for full documentation.

## Output Formatting

- Always include Jira links: `[PL-####](https://symend.atlassian.net/browse/PL-####)`
- Show issue type prefix (Bug, Task, Story, Spike)
- Include status and assignee
- Suggest next steps based on context
- Follow Symend naming conventions in all suggestions
