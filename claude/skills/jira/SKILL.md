---
name: jira
description: Jira workflows with git integration, branch naming, PR creation
---

# Jira Operations with Git Workflow

**Trigger**: When the user asks about Jira issues, wants to check tickets, start work on a ticket, create a PR, or any Jira operations.

**Goal**: Help with Jira workflows including checking tickets, starting work, creating branches, and preparing PRs with proper conventions.

## Project Conventions

These conventions adapt to your project. Replace placeholders:
- **Project Key**: `PROJ` (e.g., PL, DEV, PROJ)
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
# Update summary
bash ~/.claude/scripts/jira-rest-api.sh update PROJ-123 summary "New summary text"

# Update description
bash ~/.claude/scripts/jira-rest-api.sh update PROJ-123 description "New description"
```

### Add comment:
```bash
bash ~/.claude/scripts/jira-rest-api.sh comment PROJ-123 "Work in progress"
```

### Change status (transition):
```bash
# List available transitions
bash ~/.claude/scripts/jira-rest-api.sh transition PROJ-123

# Move to specific status
bash ~/.claude/scripts/jira-rest-api.sh transition PROJ-123 "In Progress"
bash ~/.claude/scripts/jira-rest-api.sh transition PROJ-123 "Done"
```

### Assign issue:
```bash
# Assign to yourself
bash ~/.claude/scripts/jira-rest-api.sh assign PROJ-123 me

# Assign to another user
bash ~/.claude/scripts/jira-rest-api.sh assign PROJ-123 user@example.com
```

### Manage labels:
```bash
# Add labels
bash ~/.claude/scripts/jira-rest-api.sh labels PROJ-123 add "bug,urgent"

# Remove labels
bash ~/.claude/scripts/jira-rest-api.sh labels PROJ-123 remove "needs-review"
```

### Link issues:
```bash
bash ~/.claude/scripts/jira-rest-api.sh link PROJ-123 "blocks" PROJ-456
bash ~/.claude/scripts/jira-rest-api.sh link PROJ-123 "relates to" PROJ-789
```

## Common Search Patterns

### Service/Component-Specific Searches
```bash
# Find issues by component
bash ~/.claude/scripts/jira-rest-api.sh search "project = PROJ AND component = 'Frontend'" 20

# Find issues by label
bash ~/.claude/scripts/jira-rest-api.sh search "project = PROJ AND labels = 'technical-debt'" 20

# Recent updates
bash ~/.claude/scripts/jira-rest-api.sh search "project = PROJ AND updated >= -7d ORDER BY updated DESC" 20
```

## Example Interactions

```
User: Show my issues

You: [Run mine command]
     Present as:

     You have 5 open issues:
     1. [PROJ-205](link) Task | Implement feature | In Progress
     2. [PROJ-106](link) Bug | Fix login error | To Do
     ...

User: I want to work on PROJ-137

You: [Get ticket details]
     Present:

     **PROJ-137: Add user authentication**
     Status: To Do

     Suggested branch name:
     `feature/PROJ-137_add_user_auth`

     Commands:
     ```bash
     git checkout -b feature/PROJ-137_add_user_auth
     ```

     When committing, use:
     `feat: [PROJ-137] Add user authentication`

User: Create PR for PROJ-137

You: [Get ticket]
     Generate PR template:

     **Title:** feat: [PROJ-137] Add user authentication

     **Body:**
     ## Summary
     Implement user authentication feature.

     ## Related issues
     - [PROJ-137](jira-url)

User: Find bugs in project

You: [Run search with filter]
     bash ~/.claude/scripts/jira-rest-api.sh search "project = PROJ AND type = Bug" 10
```

## Useful JQL Queries

```jql
# My active work
project = PROJ AND assignee = currentUser() AND resolution = Unresolved

# Ready for dev
project = PROJ AND status = "Ready for Dev" AND assignee is EMPTY

# Current sprint
project = PROJ AND sprint in openSprints()

# Blocked tickets
project = PROJ AND status = Blocked

# Recently completed
project = PROJ AND status = Done AND resolved >= -7d ORDER BY resolved DESC

# High priority
project = PROJ AND priority = High AND resolution = Unresolved
```

## Git Workflow Patterns

### Conventional Commits

Use these commit type prefixes:
- `feat:` - New feature
- `fix:` - Bug fix
- `refactor:` - Code refactoring
- `chore:` - Maintenance tasks
- `docs:` - Documentation changes
- `test:` - Test additions or changes
- `perf:` - Performance improvements

### Branch Naming

Pattern: `{type}/{PROJ}-{number}_{description}`

Examples:
- `feature/PROJ-123_add_login`
- `bugfix/PROJ-456_fix_crash`
- `refactor/PROJ-789_update_api`

### PR Template

```markdown
# Summary

Brief description of changes and goals.

## Related issues

- [PROJ-####](jira-url)

## Checklist

- [ ] Tests pass
- [ ] Code reviewed
- [ ] Documentation updated
- [ ] No breaking changes (or documented)

## Steps to Test

1. Step one
2. Step two
```

## Output Formatting

- Always include Jira links: `[PROJ-####](jira-url-from-config)`
- Show issue type prefix (Bug, Task, Story, Epic)
- Include status and assignee
- Suggest next steps based on context
- Follow project naming conventions in all suggestions
