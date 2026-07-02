# Lint Checklist — mandatory pass before output

Run every rule below against the assembled draft in Stage 3. For each concern: apply the
detect signal; if it fires, apply the repair action. Record checked / repaired / flagged for
the lint report.

Two outcomes are possible per concern:
- **repair** — fix it inline and note it.
- **flag** — a required input is genuinely unknown; note it and ask the user. Do not guess.

The generated prompt must pass all rules before it is shown (dogfooding).

**Run this checklist twice:** once on the assembled draft (Stage 3), and again on the exact
final emitted text (Stage 4's final-output hygiene pass). Formatting and output assembly can
reintroduce truncation/corruption or a contradiction that was not in the draft, so linting only
the draft is not sufficient — the bytes you actually present must pass.

---

## Mechanical concerns (repair inline)

### 1. Truncated words
- **Detect:** any word cut mid-token, or a line ending mid-word without punctuation.
- **Repair:** restore the full word from context.

### 2. Incomplete sentences
- **Detect:** a sentence with no verb, or one that ends without terminal punctuation where a
  full statement was intended.
- **Repair:** complete the sentence or remove the fragment.

### 3. Dangling fragments
- **Detect:** a heading, list item, or clause with no content after it; a trailing
  conjunction ("and", "so", "which") with nothing following.
- **Repair:** finish the thought or delete the fragment.

### 4. Broken commands
- **Detect:** unbalanced quotes or brackets; an obviously incomplete command; a command using
  the wrong shell for the target (this repo uses PowerShell primary and bash; check syntax
  matches the shell named in the prompt).
- **Repair:** correct the command and confirm it is runnable as written.

### 5. Broken file paths
- **Detect:** a path that cannot exist as written (typo, wrong separator, references a moved
  or non-existent file).
- **Repair:** correct the path; verify referenced Required Reading paths actually exist.

### 6. Stale copied instructions
- **Detect:** content that refers to a different task, repo, ticket, or branch than the one
  at hand; leftover text from a template that no longer applies.
- **Repair:** rewrite for the current task or remove.

---

## Structural concerns (repair from profile, or flag)

### 7. Contradictions
- **Detect:** two statements that cannot both hold (for example, "make the change" under a
  research-only mode, or "no commits" alongside a commit step).
- **Repair:** resolve in favour of the higher-precedence profile layer
  (`core < mode < repo-safe < live-gated < homebrain`).

- **High-value sub-case — write-safety contradiction (research/scope vs. write).** A prompt
  that permits a file write while framing itself as read-only or as not touching `main`. This
  admits **no** "optional" or "single-file" loophole. Watch for all of these:
  - `research-only` (or a "research agent" role) **plus** any write, create, edit, commit, or
    mutation permission — including an "optional" or "single" one — in Allowed Files / Systems
    or Required Steps;
  - "do not edit `main` directly" **plus** an allowed repository write, with no worktree
    required (a write in the `main` checkout edits `main`, committed or not);
  - "do not create branches or worktrees", **or** any statement that the worktree requirement is
    waived, **plus** an allowed repository write;
  - `research-only` **plus** a write **plus** a worktree step — a worktree does not rescue a
    research-only write; the mode itself must change to `implementation` + `repo-safe`;
  - a "read-only" Allowed Files / Systems list **plus** a write exception — a "Write (optional…",
    a "single working-tree doc", a "single optional uncommitted working-tree file", "working
    tree only, no git actions", etc.;
  - a claim that "task authorization" permits the write, used to justify a research-only or
    no-worktree write (authorization does not override profile safety unless the prompt is
    represented as `implementation` + `repo-safe`, or a claimed `live-gated` action).
- **Repair (write-safety):** apply the **Write-safety consistency** repair policy in
  `profiles.md`, in order: (1) default to chat-only with no file writes; (2) if a durable file
  is requested, **STOP and ask** whether to switch to `implementation` + `repo-safe` with a
  worktree — do not invent a writable deliverable; (3) never allow an optional working-tree
  write under research-only or a no-worktree stance — a write exception alongside "no worktree /
  no main edit", optional or not, committed or not, is never a valid output.

### 8. Unsafe git or environment rules
- **Detect:** branching or committing without a base-state check; editing `main` directly;
  destructive commands without a guard; assuming a branch or base that was not verified. Also
  fires when a repository write is permitted while worktrees/branches are forbidden or `main`
  edits are forbidden with no worktree required (the write-safety sub-case of concern 7).
- **Repair:** insert the base-safety check (local `main` equals `origin/main`, else STOP) and
  the worktree requirement from the repo-safe overlay. When the unsafe rule is a write permitted
  without a safe process, apply the **Write-safety consistency** repair policy (concern 7).

### 9. Ambiguous optional choices
- **Detect:** an instruction offering options without a decision rule ("optionally do X",
  "you may want to Y") that leaves the agent to guess.
- **Repair:** make the choice explicit, or state the exact condition under which each option
  applies.

### 10. Missing or invalid allowed-file scope
- **Detect:** the Allowed Files / Systems section is absent or empty; or it is invalid for the
  mode — for example a `research-only` prompt whose Allowed Files grants a write, or a
  "read-only" list carrying a write exception (the write-safety sub-case of concern 7).
- **Repair:** fill it from the profile and scope; **flag** and ask only if it cannot be
  reasonably inferred. If the invalidity is a write under a read-only/research stance, apply the
  **Write-safety consistency** repair policy (concern 7): default to a read-only list, or switch
  to `implementation` + `repo-safe` if a durable write is genuinely required.

### 11. Missing forbidden actions (or forbidden/allowed conflict)
- **Detect:** the Forbidden Actions section is absent or empty, or omits the active profile's
  hard rules; **or** a Forbidden Action directly conflicts with an Allowed Files / Systems or
  Required Steps permission — e.g. "do not edit `main` directly" / "do not create worktrees"
  while a repository write is allowed (the write-safety sub-case of concern 7).
- **Repair:** add the profile's forbidden actions. When a forbidden action conflicts with an
  allowed write, apply the **Write-safety consistency** repair policy (concern 7) rather than
  leaving both in place.

### 12. Missing verification
- **Detect:** the Verification section is absent or empty, or (for repo work) omits a
  changed-files check.
- **Repair:** add concrete verification commands with expected output.

### 13. Missing stop conditions
- **Detect:** the Stop Conditions section is absent or empty, or omits a stop before an
  irreversible or outward-facing action.
- **Repair:** add the profile's stop conditions.

### 14. Missing definition of done
- **Detect:** the Definition of Done section is absent, empty, or non-verifiable.
- **Repair:** add objectively checkable completion criteria.

---

## Coverage note

A deterministic script, `prompt_lint.py` (deployed to `~/.claude/scripts/`), now backstops
the mechanically checkable subset. Run it as part of Stage 3; see SKILL.md for usage.

Deterministic coverage (`prompt_lint.py`):
- unbalanced code fences
- corrupted / broken markdown tables (concern for a corrupted table cell), outside fences
- placeholder markers `TODO` / `TBD` / `FIXME` / `XXX` (relates to stale content, concern 6)
- required-section presence and non-emptiness (concerns 10, 11, 12, 13, 14) in prompt mode
- trailing-hyphen and connective-before-break signals (partial coverage of concerns 1, 2, 3)
- write-safety contradictions (the concern 7 sub-case, prompt mode only): flags
  research-only-plus-write, no-worktree-plus-write, no-main-edit-plus-write-without-worktree,
  and any explicit waiver of the worktree requirement. Write grants are detected from a range of
  phrasings (a "Write:" / "Write (optional" allowed-files bullet, "working tree only",
  "working-tree doc", "single/optional uncommitted working-tree file", "write exception")

Judgment-based, still handled by the checklist above (LLM inspection):
- broken commands (4), broken file paths (5), stale copied instructions (6) beyond marker
  words, contradictions (7) beyond the write-safety sub-case, ambiguous optional choices (9),
  and the parts of truncation and incomplete-sentence detection (1, 2) that need meaning.

The lint report should note which concerns were confirmed by `prompt_lint.py` and which were
verified by inspection.
