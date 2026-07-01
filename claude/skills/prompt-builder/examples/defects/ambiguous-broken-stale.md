# Defect example — ambiguous choices, broken command/path, stale text (SYNTHETIC)

**Source:** SYNTHETIC. Authored to exercise four related content rules in one excerpt.

**Lint concerns demonstrated:**
- 4 broken commands
- 5 broken file paths
- 6 stale copied instructions
- 9 ambiguous optional choices

**Bad excerpt:**

```
REQUIRED STEPS
1. Optionally run the tests, or skip them if you prefer.
2. Read the config at ~/dotfiles/shel/.bash_prof (source of truth).
3. Run: grep -n "alias" shell/.bash_profile | (missing close and pipe target
4. As in the PROJ-123 ticket, update the Gatekeeper.sln solution before merging.
```

**Expected verdict:** repair.

**Expected repair summary:**
- "Optionally run the tests, or skip them if you prefer" gives no decision rule -> make it
  explicit (for example, "run the tests; they must pass before proceeding") (concern 9).
- The path `~/dotfiles/shel/.bash_prof` is malformed -> correct to the real path
  `shell/.bash_profile` (concern 5).
- The grep command has an unbalanced parenthesis and no pipe target -> complete it into a
  runnable command (concern 4).
- The reference to "PROJ-123" and "Gatekeeper.sln" is stale copied text from an unrelated
  task -> remove it or replace with the current task's real reference (concern 6).
