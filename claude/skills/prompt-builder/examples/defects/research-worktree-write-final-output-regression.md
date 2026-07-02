# Defect example — research-only + worktree + optional write, emitted with truncation (REGRESSION, REAL)

**Source:** REAL regression, reconstructed from a failed clean-session `/prompt-builder` run.
Two failures occurred together and this fixture reproduces both:

1. **Write-safety loophole:** the builder kept `research-only` mode but tried to make an
   "optional decision-note" write safe by *adding a worktree step* — `research-only` + worktree
   + optional write. A worktree does not rescue a research-only write; the mode must change.
2. **Unlinted final output:** the emitted prompt contained truncation/corruption artifacts even
   though the builder claimed lint passed — it linted a scratchpad draft, not the final text.

**Lint concerns demonstrated:**
- 1 truncated words, 2 incomplete sentences, 3 dangling fragments (in the *emitted* text)
- 4 broken commands
- 7 contradictions (write-safety sub-case: research-only + write, even with a worktree)
- 8 unsafe git or environment rules
- 10 missing/invalid allowed-file scope
- 11 forbidden actions conflict with allowed actions

**Bad excerpt (the emitted final prompt — note the artifacts):**

```
ROLE
You are a research agent evaluating a Z-Wave adapter acquisition for the HomeBrain stack. You
investigate public sources and the local docs, then recommend whether to acquire.

GOAL
Recommend whether to acquire the ZWA-2 Z-Wave adapter, with a short rationale.

CONTEXT
This is a research-only acquisition-decision task for the HomeBrain repositor-
The task authorization permits producing a decision note if one is warranted.

INPUTS / REQUIRED READING
1. docs/homebrain/ONBOARDING.md — current state.
2. Public vendor and retailer pages for the adapter.

SCOPE
In scope: research, a recommendation, and optionally a short decision note. Out of scope: and

ALLOWED FILES / SYSTEMS
- Read-only: all files under docs/homebrain/, and public vendor/retailer pages.
- Write (optional): a single decision note under docs/homebrain/ if a note is warranted.

FORBIDDEN ACTIONS
- Do not stage, commit, or push anything unless separately approved.
- Do not edit main directly.

REQUIRED STEPS
1. Confirm local main equals origin/main.
2. Create a worktree so the optional note can be written safely: git worktree add
3. Investigate the public sources and the local docs, then recommend.
4. Optionally, if a note is warranted, write it and check it with: grep -n zwa docs/homebrain/ | (

VERIFICATION
Cite the sources read and confirm the recommendation against them.

STOP CONDITIONS
- If a live change appears required, STOP and ask.

DEFINITION OF DONE
- A recommendation is delivered, with the optional decision note written if warranted.

EXPECTED FINAL REPORT
- The recommendation, the sources, and whether the optional note was written.
```

**Expected verdict:** repair — but the correct repair is **not** to keep this shape. Default to
chat-only/no writes, or STOP and ask whether to switch to `implementation` + `repo-safe` +
worktree.

**Expected repair summary:**
- **Write-safety (concern 7):** the prompt is `research-only` yet grants an optional write. The
  worktree step does **not** make this valid — `research-only` + worktree + write is forbidden.
  Repair: default to chat-only (remove the write and the worktree step, keep the list read-only),
  or STOP and ask whether to switch the mode to `implementation` + `repo-safe`. Also trips 8, 10, 11.
- **Truncation/corruption (concerns 1, 2, 3), which a final-output hygiene pass must catch:**
  - CONTEXT ends on `repositor-` — a truncated word.
  - SCOPE's "Out of scope:" line ends on the dangling connective `and` with nothing after it.
  - REQUIRED STEPS step 2 ends mid-command at `git worktree add` (no arguments).
- **Broken command (concern 4):** step 4's `grep -n zwa docs/homebrain/ | (` has an unbalanced
  parenthesis and no pipe target.
- **Process fix:** these artifacts survived because only a draft was linted. The final emitted
  text must be linted (Stage 4 final-output hygiene pass) before it is shown.

**Deterministic detection:** `prompt_lint.py --prompt` on this emitted text flags the write-safety
contradiction (research-only + write) plus the truncation/dangling signals (trailing hyphen on
`repositor-`, and the connective-before-break on the `and` line).
