# Defect example — unsafe git assumptions (SYNTHETIC)

**Source:** SYNTHETIC. Authored to exercise the unsafe-git rule; no real example was
available for this class.

**Lint concerns demonstrated:**
- 8 unsafe git or environment rules

**Bad excerpt:**

```
REQUIRED STEPS
1. Checkout main and create a feature branch from it: git checkout -b my-feature
2. Make the change directly on the branch.
3. Commit and merge into main.
```

**Expected verdict:** repair.

**Expected repair summary:**
- The prompt branches without confirming the base is current. Insert the base-safety check
  first: confirm local `main` equals `origin/main`; if not, STOP and report.
- It works on a branch created off a possibly-stale main and merges back without isolation.
  Require an isolated worktree under `.claude/worktrees/` and forbid editing `main` directly.
- Add the repo-safe stop condition: stop before any commit, push, or merge and wait for
  approval.
