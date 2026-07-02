# Defect example — research-only with an "optional" working-tree write and a waived worktree (REGRESSION, REAL)

**Source:** REAL regression. This is a generated prompt-builder output that slipped through an
earlier version of the write-safety rule. It is `research-only`, yet it grants an *optional*
working-tree write, forbids editing `main`, and explicitly *waives* the repo-safe worktree
requirement — the exact contradiction the write-safety invariant exists to prevent. Captured
here so the rule and the deterministic linter never regress on this phrasing again.

**Why the earlier rule missed it:** the write grant was phrased as "Write (optional …)" and the
worktree was removed by an explicit *waiver* ("the worktree requirement was intentionally
waived") rather than a "do not create worktrees" prohibition. The linter's write-carve-out
phrases and worktree signal did not cover these wordings.

**Lint concerns demonstrated:**
- 7 contradictions (write-safety sub-case — the governing concern)
- 8 unsafe git or environment rules (a repository write with the worktree requirement waived)
- 10 missing/invalid allowed-file scope (a "read-only" list carrying an optional write)
- 11 forbidden actions conflict with allowed actions (no worktree / no main edit vs. an allowed write)

**Bad excerpt:**

```
ROLE
You are a research agent evaluating a Z-Wave adapter acquisition for the HomeBrain stack. You
investigate public sources and the local docs, then recommend whether to acquire.

GOAL
Recommend whether to acquire the Z-Wave adapter, with a short rationale.

CONTEXT
This is a research-only acquisition-decision task. The task authorization permits producing a
decision note if one is warranted.

INPUTS / REQUIRED READING
1. docs/homebrain/ONBOARDING.md — current state.
2. Public vendor and retailer pages for the adapter.

SCOPE
In scope: research and a recommendation. Out of scope: buying anything; any live change.

ALLOWED FILES / SYSTEMS
- Read-only: all files under docs/homebrain/, and public vendor/retailer web pages.
- Write (optional, single optional uncommitted working-tree file): a working-tree doc at
  docs/homebrain/2026-07-01-rq-06-zwa-2-acquisition-check.md, only if a decision note is warranted.

FORBIDDEN ACTIONS
- Do not stage, commit, or push anything unless separately approved.
- Do not edit main directly; the worktree requirement was intentionally waived for this single
  optional uncommitted working-tree file.

REQUIRED STEPS
1. Investigate the public sources and the local docs.
2. Optionally write the working-tree doc if a decision note is warranted; otherwise recommend in chat.

VERIFICATION
Cite the sources read and confirm the recommendation against them.

STOP CONDITIONS
- If a live change appears required, STOP and ask.

DEFINITION OF DONE
- A recommendation is delivered, with the optional decision note written if warranted.

EXPECTED FINAL REPORT
- The recommendation, the sources, and whether the optional note was written.
```

**Expected verdict:** repair (default to chat-only), or STOP and ask if a durable note is
actually wanted.

**Expected repair summary:**
- This is a contradiction (concern 7, write-safety sub-case): the prompt is `research-only` and
  read-only, forbids `main` edits, and waives the worktree requirement, yet grants an optional
  working-tree write. An "optional" or "uncommitted" write in the main checkout still edits
  `main`; the worktree requirement cannot be waived. It also trips concerns 8, 10, and 11.
- The "task authorization permits producing a decision note" does **not** license this: an
  authorization only counts if the prompt is represented as `implementation` + `repo-safe` (or a
  claimed live action). It cannot turn a research-only prompt into one that writes files.
- **Default repair (chat-only):** remove the optional write and the waiver; keep the Allowed
  Files / Systems list read-only; deliver the recommendation in chat.
- **If a durable decision note is wanted:** STOP and ask whether to switch the prompt to
  `implementation` + `repo-safe` with a worktree (base-state check → `git worktree add …` →
  then write). Do not invent the writable deliverable or keep the carve-out.
- Never keep an optional working-tree write under a research-only / no-worktree / waived-worktree
  stance — optional or not, committed or not, it is never a valid output.

**Deterministic detection:** `prompt_lint.py --prompt` flags this via the write-safety checks —
the worktree-waiver signal ("the worktree requirement was intentionally waived"), research-only +
write ("Write (optional …" / "single optional uncommitted working-tree file"), and the broadened
write-carve-out phrasings.
