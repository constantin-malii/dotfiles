---
name: jira
description: Jira issue management with git workflow integration. Use when the user asks about Jira issues, wants to check tickets, start work on a ticket, search issues, create/update tickets, manage labels, link issues, or any Jira operations. Also triggers on issue key patterns like PROJ-123.
argument-hint: [command] [args...]
allowed-tools: Bash Read Grep Glob
---

# Jira Operations with Git Workflow

If arguments are provided, interpret them as a command:
- `/jira get PROJ-123` → run `bash ~/.claude/scripts/jira-rest-api.sh get PROJ-123`
- `/jira mine` → run `bash ~/.claude/scripts/jira-rest-api.sh mine`
- `/jira search "project = PROJ AND status = Open"` → run search

When invoked with arguments: `bash ~/.claude/scripts/jira-rest-api.sh $ARGUMENTS`

## Project Conventions

These conventions adapt to your project. Replace placeholders:
- **Project Key**: `PROJ` (e.g., PL, DEV, WEMC)
- **Branch Format**: `feature/{PROJ}-{number}_{description}` (lowercase with underscores)
- **Commit Format**: `{type}: [{PROJ}-{number}] {Description}`
- **PR Format**: `{type}: [{PROJ}-{number}] {Description}`

## How to Help

### When user asks to see their issues:
```bash
bash ~/.claude/scripts/jira-rest-api.sh mine
```
Format as numbered list with links to Jira.

### When user asks about specific ticket:
```bash
bash ~/.claude/scripts/jira-rest-api.sh get PROJ-123
```
Show key details: Summary, Status, Assignee, Description.

### When user wants to start work on a ticket:
1. Get ticket details
2. Suggest branch name: `feature/{PROJ}-{number}_{descriptive_name}`
3. Show git commands:
   ```bash
   git checkout -b feature/PROJ-123_add_feature
   ```
4. Remind about commit format: `feat: [PROJ-123] Add feature`

### When user wants to create PR for a ticket:
1. Get ticket details
2. Suggest PR title: `{type}: [{PROJ}-{number}] {Summary}`
3. Generate PR body with Jira link:
   ```markdown
   ## Summary
   {Brief description}

   ## Related issues
   - [{PROJ}-###](#) (use actual Jira URL from config)

   ## Checklist
   - [ ] Tests pass
   - [ ] Code reviewed
   ```

## Create and Update Operations

### Create a new issue:
```bash
bash ~/.claude/scripts/jira-rest-api.sh create PROJ "Bug fix for login" "User cannot login when..." Bug
```

### Update issue:
```bash
bash ~/.claude/scripts/jira-rest-api.sh update PROJ-123 summary "New summary text"
bash ~/.claude/scripts/jira-rest-api.sh update PROJ-123 description "New description"
```

### Add comment:
```bash
bash ~/.claude/scripts/jira-rest-api.sh comment PROJ-123 "Work in progress"
```

### Change status (transition):
```bash
bash ~/.claude/scripts/jira-rest-api.sh transition PROJ-123
bash ~/.claude/scripts/jira-rest-api.sh transition PROJ-123 "In Progress"
bash ~/.claude/scripts/jira-rest-api.sh transition PROJ-123 "Done"
```

### Assign issue:
```bash
bash ~/.claude/scripts/jira-rest-api.sh assign PROJ-123 me
bash ~/.claude/scripts/jira-rest-api.sh assign PROJ-123 user@example.com
```

### Manage labels:
```bash
bash ~/.claude/scripts/jira-rest-api.sh labels PROJ-123 add "bug,urgent"
bash ~/.claude/scripts/jira-rest-api.sh labels PROJ-123 remove "needs-review"
```

### Link issues:
```bash
bash ~/.claude/scripts/jira-rest-api.sh link PROJ-123 "blocks" PROJ-456
bash ~/.claude/scripts/jira-rest-api.sh link PROJ-123 "relates to" PROJ-789
```

## Common Search Patterns

```bash
bash ~/.claude/scripts/jira-rest-api.sh search "project = PROJ AND component = 'Frontend'" 20
bash ~/.claude/scripts/jira-rest-api.sh search "project = PROJ AND labels = 'technical-debt'" 20
bash ~/.claude/scripts/jira-rest-api.sh search "project = PROJ AND updated >= -7d ORDER BY updated DESC" 20
```

## Example Interactions

```
User: Show my issues
You: [Run mine command, present as numbered list with links]

User: I want to work on PROJ-137
You: [Get ticket, suggest branch name, show git checkout command]

User: Create PR for PROJ-137
You: [Get ticket, suggest PR title and body with Jira link]

User: Find bugs in project
You: bash ~/.claude/scripts/jira-rest-api.sh search "project = PROJ AND type = Bug" 10
```

## Useful JQL Queries

```jql
project = PROJ AND assignee = currentUser() AND resolution = Unresolved
project = PROJ AND status = "Ready for Dev" AND assignee is EMPTY
project = PROJ AND sprint in openSprints()
project = PROJ AND priority = High AND resolution = Unresolved
project = PROJ AND status = Done AND resolved >= -7d ORDER BY resolved DESC
```

## Git Workflow Patterns

### Conventional Commits
- `feat:` - New feature
- `fix:` - Bug fix
- `refactor:` - Code refactoring
- `chore:` - Maintenance tasks
- `docs:` - Documentation changes
- `test:` - Test additions or changes
- `perf:` - Performance improvements

### Branch Naming
Pattern: `{type}/{PROJ}-{number}_{description}`
- `feature/PROJ-123_add_login`
- `bugfix/PROJ-456_fix_crash`
- `refactor/PROJ-789_update_api`

## Output Formatting

- Always include Jira links: `[PROJ-####](jira-url-from-config)`
- Show issue type prefix (Bug, Task, Story, Epic)
- Include status and assignee
- Suggest next steps based on context
