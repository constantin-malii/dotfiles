# Golden example — research-only mode

**Rough intent:** "Find out how skills get deployed to `~/.claude` and whether adding a new
skill dir needs an install.sh change."

**Profile:** mode `research-only`, no overlays.

**Why it is golden:** read-only posture, no mutating actions, verification by source
citation, findings-only definition of done.

```
ROLE
You are a research agent inspecting the dotfiles repo at D:\repos\dotfiles. You investigate
and report; you do not change anything.

GOAL
Determine how install.sh deploys skills to ~/.claude and whether a new skill directory
requires any install.sh change.

CONTEXT
Skills live under claude/skills/<name>/ and are deployed by install.sh. We want to know if
adding a new skill dir is picked up automatically or needs a code change.

INPUTS / REQUIRED READING
1. install.sh — the deploy logic, especially the skills copy step.
2. docs/claude-code-workflow.md — how skills are described and invoked.

SCOPE
In scope: reading and explaining the deploy mechanism. Out of scope: editing any file,
running install.sh, or deploying anything.

ALLOWED FILES / SYSTEMS
Read-only access to the repository. No systems may be acted on.

FORBIDDEN ACTIONS
- No file edits, no file creation, no mutating commands.
- No commits, no pushes.
- No running of install.sh or any deploy step.

REQUIRED STEPS
1. Read install.sh and locate the skills copy step.
2. Read docs/claude-code-workflow.md for the deployment description.
3. Summarize whether a new skill dir is auto-deployed or needs a change, citing line numbers.

VERIFICATION
Quote the exact install.sh line(s) that copy skills and confirm the finding against the file
actually read. State the line numbers.

STOP CONDITIONS
- If a referenced file does not exist, STOP and report which path is missing.
- If asked to change or run anything, STOP — this task is read-only.

DEFINITION OF DONE
- A clear answer (auto-deployed or needs change) with the exact citation.
- No files changed and no commands with side effects were run.

EXPECTED FINAL REPORT
- The answer with cited line numbers.
- Any caveats (for example, edge cases the mechanism does not cover).
```

Lint report
- Profile: research-only (no overlays)
- Checked: all 15 concerns
- Repaired: nothing
- Flagged (needs your input): none
- Mechanical checks: by inspection (deterministic script arrives in Increment 3)
