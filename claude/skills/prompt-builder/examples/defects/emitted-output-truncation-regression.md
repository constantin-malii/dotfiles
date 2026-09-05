# Defect example — correct write-safety, but corrupted visible output was emitted (REGRESSION, REAL)

**Source:** REAL regression from a clean-session `/prompt-builder` run. The write-safety
behaviour was correct — the builder rejected the research-only + optional-write request and
defaulted to a chat-only research prompt with a STOP condition about re-scoping as
`implementation` + `repo-safe` + worktree. **But the final emitted prompt shown to the user was
riddled with truncation/corruption** (mid-word cuts and mashed words), and the lint report still
claimed clean. The deterministic linter reported clean because its truncation signals only cover
trailing-hyphen / connective-before-break, not arbitrary mid-word cuts.

This fixture exists to enforce: the exact visible output must be read; if corrupted, the process
must STOP and re-render, and the lint report may not claim clean.

**Lint concerns demonstrated:**
- 1 truncated words (mid-word), 2 incomplete sentences, 3 dangling fragments — in the *emitted* text
- plus the process failure: a "clean" lint report over corrupted visible output

**Bad excerpt (the emitted final prompt — heavily corrupted; this must never be shown):**

```
ROLE
You are a research agent evaluating a Z-Wave adapter acquisition for the HomeBrai stack. You
investigate public sources and repor, and you do not chang any file.

GOAL
Recommend whether to acquire the ZWA-2 and comp the option aon the vendor evidence.

CONTEXT
This task is t mode only. We weigh the ZWA-2 agains what is in docs/homebrai during the
research, and touch no live hos or Music Assistect service.

INPUTS / REQUIRED READING
1. docs/homebrain/ONBOARDING.md for the current stat.
2. vari public vendor and retailer pages for the ZWA-2.

SCOPE
In scope: research and a recommendation. Out of scope: any file write, worktree, or we

ALLOWED FILES / SYSTEMS
- Read-only: all files under docs/homebrai, and public vendor pages. No writes.

FORBIDDEN ACTIONS
- No file edits, no file creation, no commits, no push, no live chang.

REQUIRED STEPS
1. Read the required docs and the vari vendor pages.
2. Weigh the ZWA-2 and deliver the recommendation in chat; write nothing if a note is wantrain.

VERIFICATION
Cite the sources and confirm the recommendation aon them.

STOP CONDITIONS
- If a durable decision note is wanted, STOP and ask to re-scope as implementation + repo-safe + worktree.

DEFINITION OF DONE
- A recommendation is delivered in chat, with no repository chang.

EXPECTED FINAL REPORT
- The recommendation, the sources, and any open question duri the review.
```

**Expected verdict:** STOP — do not emit. Re-render the prompt from the assembled content and
re-run the final-output hygiene pass; only emit once the visible text is clean.

**Expected repair summary:**
- **Write-safety (concerns 7/8/10/11): already correct.** The prompt is chat-only, read-only,
  no writes, no worktree; the STOP condition correctly points to `implementation` + `repo-safe` +
  worktree if a durable note is wanted. This part passes.
- **Output hygiene (concerns 1, 2, 3): failed.** The emitted text is corrupted:
  - Mid-word truncations: `HomeBrai` (HomeBrain), `repor` (report), `chang` (change/changes),
    `comp` (compare), `aon` (on / against), `t mode` (research-only), `agains` (against),
    `homebrai` (homebrain), `hos` (host), `Assistect` (Assistant), `stat` (state), `vari`
    (various), `duri` (during).
  - Mashed / dropped-boundary tokens: `wantrain`, and lines ending mid-thought (`or we`).
- **Process fix:** these survived because only a draft was linted and a clean `prompt_lint.py`
  run was trusted. The Stage 4 final-output hygiene pass must read the exact visible text; a clean
  deterministic result does not authorize emission. On finding corruption, STOP and re-render —
  never emit, and never let the lint report say "clean".

**Deterministic detection:** `prompt_lint.py --prompt` flags the known-term truncations
`HomeBrai` and `homebrai` (-> `HomeBrain`). It does **not** catch the other mid-word cuts
(`repor`, `comp`, `aon`, `Assistect`, `t mode`, `wantrain`, `or we`, …) — which is exactly why
the manual visible-text read is the authoritative gate and the process must STOP on any
corruption rather than trusting a "clean" script result.
