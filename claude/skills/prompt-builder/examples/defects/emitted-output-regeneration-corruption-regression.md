# Defect example — corruption from regenerating the prompt instead of emitting the linted file (REGRESSION, REAL)

**Source:** REAL regression from a clean-session `/prompt-builder` run. The write-safety
behaviour was correct — the builder defaulted to a chat-only `research-only` prompt with zero
repository writes and a STOP condition to re-scope as `implementation` + `repo-safe` + worktree
if a durable doc is wanted. **But the final visible prompt shown to the user was corrupted**
(mid-word cuts and mashed words throughout), while the lint report falsely claimed the visible
text was clean.

**Root cause:** the builder linted one copy of the prompt and then *regenerated / re-typed* the
prompt into its reply. The lint ran on the clean copy; the visible copy was a fresh,
corrupted one. The lint report's "clean" was true of the checked artifact but not of the emitted
artifact.

**Fix this fixture enforces:** write the final prompt to a file, lint and read *that file*, and
emit the file's exact bytes verbatim (`cat`). Never compose the visible prompt separately from
the linted artifact. A "clean" claim is valid only for the exact bytes shown.

**Lint concerns demonstrated:**
- 1 truncated words (mid-word), 2 incomplete sentences, 3 dangling fragments — in the *emitted* text
- process failure: a "clean" lint report over corrupted visible output, because the emitted text
  was regenerated rather than printed verbatim from the linted file

**Bad excerpt (the emitted final prompt — corrupted by regeneration; this must never be shown):**

```
ROLE
You are a research-oires dispatch/exent agent for the HomeBrai stack. You investigate and
recommend; you make no repository chang.

GOAL
Recommend whether to acquire the ZWA-2 and deliver a checkmended option, st; with zero writes.

CONTEXT
The HomeBrai controller ne has no Z-Wave coordinator today. We weigh the ZWA-2 duri the review
against docs/homebrain notes; this is researcebrain and read-only.

INPUTS / REQUIRED READING
1. docs/homebrain/ONBOARDING.md — read f the current state.
2. RQ-06 decking notes and vari public vendor pages.

SCOPE
In scope: proving the r recommendation. Out of scope: thng a doc, or any repository write.

ALLOWED FILES / SYSTEMS
- Read-only: docs/homebrain and public vendor pages for the US regio. No writes.

FORBIDDEN ACTIONS
- No file edits, no docont creation, no commits, no push.

REQUIRED STEPS
1. Confirm the ZWA-2 is a 908.42 MHzd variantnt for the US regio on the 908.42 Mty band.
2. Compare the alternattionale Z-Wapec options in c and recommend.

VERIFICATION
Cite sources and confirm word byn word against the pages; run fence baation checks.

STOP CONDITIONS
- If a durable doc is wanted, STOP and re-scope as implementation + repo-safe + worktree.

DEFINITION OF DONE
- A recommendation delivered in chat with no repository chang.

EXPECTED FINAL REPORT
- The recommendation, the sources, and the next actio.
```

**Expected verdict:** STOP — do not emit. The write-safety shape is fine, but the visible text is
corrupted; the lint report must not claim clean.

**Expected repair summary:**
- **Write-safety (concerns 7/8/10/11): already correct.** Chat-only, read-only, zero writes, no
  worktree; the STOP condition correctly points to `implementation` + `repo-safe` + worktree if a
  durable doc is wanted. This part passes.
- **Output hygiene (concerns 1, 2, 3): failed.** The emitted text is riddled with corruption:
  `research-oires` (research-only), `dispatch/exent` (dispatch agent), `HomeBrai` (HomeBrain),
  `chang` (change), `checkmended` (recommended), `ne has` (one has / node has), `duri` (during),
  `researcebrain` (research / HomeBrain mashed), `read f` (read for), `RQ-06 decking` (RQ-06
  doc/deck), `proving the r` (providing the), `thng a doc` (writing a doc), `regio` (region),
  `docont` (document/doc), `908.42 MHzd` / `908.42 Mty` (908.42 MHz), `variantnt` (variant),
  `alternattionale` (alternative), `Z-Wapec` (Z-Wave spec), `in c` (incomplete), `word byn`
  (word by word), `fence baation` (fence balance), `next actio` (next action), `st;` (fragment).
- **Root cause / process fix:** the visible prompt was regenerated separately from the checked
  copy. The Stage 4 process must write the prompt to a file, lint and read *that file*, and emit
  the file's exact bytes verbatim; the lint report may claim clean only for those exact bytes. On
  any corruption or any divergence between the file and the visible text, STOP and re-render —
  never emit, and never report clean.

**Deterministic detection:** `prompt_lint.py --prompt` flags the known-term truncation `HomeBrai`
(-> `HomeBrain`). It does **not** catch the many other mid-word/mashed corruptions
(`research-oires`, `checkmended`, `variantnt`, `alternattionale`, `Z-Wapec`, …) — which is why the
authoritative gate is emitting verbatim from a linted file and reading that file, not trusting a
"clean" script result over a separately-typed answer.
