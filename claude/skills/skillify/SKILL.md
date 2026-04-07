---
name: skillify
description: Analyzes the current session and converts the workflow into a reusable SKILL.md file. Invoke at the end of any session where a repeatable workflow was discovered or refined.
---

# Skillify

You are analyzing the current conversation to extract a repeatable workflow and codify it as a reusable Claude Code skill.

## Step 1: Session Analysis

Review the conversation and identify:

- **What repeatable process was performed?** Look for multi-step workflows that were executed more than once or that the user indicated should be repeatable.
- **What tools and permissions were used?** List every tool invoked: file reads, bash commands, web fetches, agent dispatches, etc.
- **Were agents dispatched?** If so, what were their specific roles and instructions?
- **What did the user provide as input?** These become the skill's parameters.
- **What are the outputs or end states?** These become the skill's success criteria.
- **What decisions required human judgment?** These become explicit pause points in the skill.

## Step 2: Clarification

Before writing the skill, ask the user these questions one at a time:

1. What should this skill be named? (use kebab-case, e.g. `deploy-review`, `issue-triage`)
2. Write one sentence describing what this skill does. This appears in Claude's skill selection UI.
3. Are there any steps that must remain manual and should not be automated?
4. Should this be global (committed to dotfiles, available everywhere) or project-specific (saved to `.claude/skills/` in the current repo)?

## Step 3: Generate the Skill

Write a complete SKILL.md file following this structure:

```
---
name: <kebab-case-name>
description: <one sentence — this is what Claude reads to decide when to invoke the skill>
---

# <Skill Title>

<One paragraph explaining what this skill does and when to use it.>

## Prerequisites
<List any required tools, credentials, or setup — omit if none>

## Steps

### Step 1: <Action>
<Exact instructions. Include commands, expected outputs, and what to do if it fails.>

### Step 2: <Action>
...

## Verification
<How to confirm the skill completed successfully>

## Example
<A concrete example invocation and what the output looks like>
```

Rules for the generated skill:
- Every step must be actionable with exact commands, not vague descriptions
- Include expected output for every command so the reader knows if it worked
- Mark human confirmation points explicitly: "**STOP — confirm with user before proceeding**"
- Skills must be idempotent where possible (safe to run twice)
- Do not invent steps that did not happen in the session

## Step 4: Present and Save

Show the generated SKILL.md to the user and wait for approval.

If they request changes, revise and show again. Repeat until approved.

Once approved, save based on their answer in Step 2 question 4:

**Global (dotfiles):**
```bash
mkdir -p ~/repos/dotfiles/claude/skills/<name>
# Write the approved SKILL.md to ~/repos/dotfiles/claude/skills/<name>/SKILL.md
bash ~/repos/dotfiles/install.sh
git -C ~/repos/dotfiles add claude/skills/<name>/
git -C ~/repos/dotfiles commit -m "feat: add <name> skill"
git -C ~/repos/dotfiles push
```

**Project-specific:**
```bash
mkdir -p .claude/skills/<name>
# Write the approved SKILL.md to .claude/skills/<name>/SKILL.md
git add .claude/skills/<name>/SKILL.md
git commit -m "chore: add <name> skill"
```

Tell the user where the file was saved and how to invoke it (`/<name>`).
