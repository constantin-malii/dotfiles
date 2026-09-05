# Defect example — truncation and corruption (REAL)

**Source:** REAL. A trimmed, redacted excerpt representative of the corruption seen in this
session's earlier planning report (the artifact that motivated this skill). Reproduced only
as much as needed to exercise the relevant lint rules.

**Lint concerns demonstrated:**
- 1 truncated words
- 2 incomplete sentences
- 3 dangling fragments
- (also a corrupted table cell, which surfaces as broken structure)

**Bad excerpt:**

```
### Recommended component form

The best form is a ski that bundles references and examp. It gives auto-invocation and

| Form | Verdict | Reasoning |
|---|---|
| Skill | Recommended | Interactive gener |
| Command |  |
| Agent | Rejected | Agents are autonomous doers dispatched to

Reasoning: because the description field is what Claude reads to
```

**Expected verdict:** repair.

**Expected repair summary:**
- "ski" -> "skill"; "examp" -> "examples"; "gener" -> "generator" (concern 1).
- Complete the sentence "It gives auto-invocation and ..." and "Reasoning: because the
  description field is what Claude reads to ..." (concern 2).
- Remove or finish the dangling "and" at the end of the first line and the trailing
  "dispatched to" clause (concern 3).
- Repair the table: the header row has three columns but the divider and cells are
  mismatched; the Command row is empty. Restore three aligned columns with real content, or
  remove the row if there is nothing to say (corrupted table cell).
