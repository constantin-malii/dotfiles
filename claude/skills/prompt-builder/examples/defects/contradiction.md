# Defect example — internal contradiction (SYNTHETIC)

**Source:** SYNTHETIC. Authored to exercise the contradiction rule and the profile
precedence resolution.

**Lint concerns demonstrated:**
- 7 contradictions

**Bad excerpt:**

```
ROLE
You are a research agent. You investigate and report only; you do not change anything.

FORBIDDEN ACTIONS
- No file edits, no commits.

REQUIRED STEPS
1. Edit src/config.yaml to fix the value.
2. Commit and push the change.
```

**Expected verdict:** repair.

**Expected repair summary:**
- The mode is `research-only`, which forbids edits and commits, but the Required Steps edit,
  commit, and push. This cannot hold (concern 7).
- Resolve in favour of the higher-precedence layer. Here the mode is the governing choice:
  either keep `research-only` and remove the editing/committing steps (report the needed
  change instead), or, if the task truly needs to change the file, switch the mode to
  `implementation` and add the repo-safe overlay, worktree step, verification, and stop
  conditions.
- State the resolved intent explicitly so no contradiction remains.
