# Defect example — missing required sections (SYNTHETIC)

**Source:** SYNTHETIC. Authored to exercise the structural-completeness rules.

**Lint concerns demonstrated:**
- 10 missing allowed-file scope
- 11 missing forbidden actions
- 12 missing verification
- 13 missing stop conditions
- 14 missing definition of done

**Bad excerpt:**

```
ROLE
You are an agent that fixes the login bug.

GOAL
Fix the login bug.

CONTEXT
Users cannot log in.

INPUTS / REQUIRED READING
1. src/auth.js

SCOPE
Fix the bug.

REQUIRED STEPS
1. Find the bug and fix it.

EXPECTED FINAL REPORT
Say what you changed.
```

**Expected verdict:** repair, with flag if Allowed Files cannot be inferred.

**Expected repair summary:**
- Allowed Files / Systems is absent -> add it, inferred from scope (for example,
  `src/auth.js` and related test files). If it genuinely cannot be inferred, flag and ask
  (concern 10).
- Forbidden Actions is absent -> add the active profile's hard rules (concern 11).
- Verification is absent -> add concrete commands with expected output, including a
  changed-files check for repo work (concern 12).
- Stop Conditions is absent -> add triggers, including a stop before irreversible or
  outward-facing actions (concern 13).
- Definition of Done is absent -> add objectively checkable criteria (concern 14).
