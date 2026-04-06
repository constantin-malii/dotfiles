---
name: azure-devops
description: Azure DevOps pull request management. Use when the user asks to create a PR, push and create PR, list PRs, check PR status, add reviewers, complete or abandon a pull request, or any Azure DevOps git operations.
argument-hint: [command] [args...]
allowed-tools: Bash Read Grep Glob
---

# Azure DevOps Pull Request Operations

If arguments are provided, interpret them as a command:
- `/azure-devops list-prs` → run `bash ~/.claude/scripts/azure-devops-rest-api.sh list-prs`
- `/azure-devops get-pr 916` → run `bash ~/.claude/scripts/azure-devops-rest-api.sh get-pr 916`
- `/azure-devops create-pr feature/branch master_6.0.x "Title" "Desc"` → run create-pr

When invoked with arguments: `bash ~/.claude/scripts/azure-devops-rest-api.sh $ARGUMENTS`

Requires: git repo with Azure DevOps remote (visualstudio.com or dev.azure.com), git credential manager configured. Auth and repo info are auto-detected from git remote origin.

## How to Help

### When user asks to create a PR:
1. Detect current branch: `git branch --show-current`
2. Determine target branch (default: main branch for the project)
3. Extract ticket number from branch name if present (e.g., `feature/WEMC-1171_desc` → `WEMC-1171`)
4. Analyze commits since divergence: `git log TARGET..HEAD --oneline` and `git diff TARGET...HEAD`
5. Suggest PR title: `{type}: [{TICKET}] {Summary}`
6. Build description with Summary, Test plan, Related issues
7. Push branch if needed: `git push -u origin BRANCH`
8. Create PR:
```bash
bash ~/.claude/scripts/azure-devops-rest-api.sh create-pr "source-branch" "target-branch" "Title" "Description"
```

### When user asks to list PRs:
```bash
bash ~/.claude/scripts/azure-devops-rest-api.sh list-prs
bash ~/.claude/scripts/azure-devops-rest-api.sh my-prs
bash ~/.claude/scripts/azure-devops-rest-api.sh list-prs completed
```

### When user asks about a specific PR:
```bash
bash ~/.claude/scripts/azure-devops-rest-api.sh get-pr 916
```
Show: title, status, merge status, branches, author, description, reviewers.

### When user wants to add reviewers:
```bash
bash ~/.claude/scripts/azure-devops-rest-api.sh add-reviewers 916 user@example.com
```

### When user wants to complete a PR:
```bash
bash ~/.claude/scripts/azure-devops-rest-api.sh complete-pr 916          # squash (default)
bash ~/.claude/scripts/azure-devops-rest-api.sh complete-pr 916 merge    # regular merge
bash ~/.claude/scripts/azure-devops-rest-api.sh complete-pr 916 rebase   # rebase
```

### When user wants to abandon a PR:
```bash
bash ~/.claude/scripts/azure-devops-rest-api.sh abandon-pr 916
```

## Branch to PR Title Convention

Extract ticket and type from branch name:
- `feature/WEMC-1171_dual_id_logging` → `feat: [WEMC-1171] Add dual ID logging`
- `bugfix/WEMC-456_fix_crash` → `fix: [WEMC-456] Fix crash`
- `refactor/WEMC-789_update_api` → `refactor: [WEMC-789] Update API`

Branch prefix mapping:
- `feature/` → `feat:`
- `bugfix/` or `fix/` → `fix:`
- `refactor/` → `refactor:`
- `chore/` → `chore:`
- `test/` → `test:`

## PR Description Template

```markdown
## Summary
- Brief bullet points describing what changed and why

## Test plan
- [ ] Unit tests pass
- [ ] Manual verification steps

## Related issues
- [TICKET-####](jira-url)
```

## Example Interactions

```
User: create a PR
You: [Detect branch, analyze commits, push if needed, create PR, return URL]

User: list my open PRs
You: [Run my-prs, present as numbered list with IDs and titles]

User: check PR 916
You: [Run get-pr, show title, status, merge status, reviewers]

User: complete PR 916
You: [Run complete-pr with squash, confirm completion]
```

## Output Formatting

- Always include PR URL in output
- Show PR ID with `#` prefix: `#916`
- Show merge status: `Succeeded`, `Conflicts`, `Queued`
- Show reviewer votes: `Approved`, `Rejected`, `No vote`
- Use branch short names (strip `refs/heads/` prefix)
