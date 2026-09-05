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

**The visible-text read is authoritative; the deterministic script is only a backstop.**
`prompt_lint.py` catches trailing-hyphen, connective-before-break, and a few known-term
prefixes, but it does **not** catch arbitrary mid-word truncation (`HomeBrai`, `Assistan`) or
mashed words (`wantrain`, `t mode`). So a clean `prompt_lint.py` run does **not** mean the output
is clean. You must read the exact emitted text yourself. **If the visible output is corrupted,
STOP and re-render — never emit it, and never let the lint report claim "clean".** A lint report
that says "clean" over corrupted visible text is itself a defect.

**What you lint must be what you emit (verbatim-from-file).** The corruption that keeps slipping
through is introduced when the prompt is *regenerated/re-typed* into the reply after being
checked: the lint runs on a clean copy, but the visible copy is a fresh, corrupted one. Prevent
it structurally — write the final prompt to a file, lint and read *that file*, then emit the
file's exact bytes verbatim (`cat`). Never compose the visible prompt separately from the linted
artifact. A lint report may claim "clean" only about the exact bytes shown, and only if those
bytes came verbatim from the linted file.

---

## Mechanical concerns (repair inline)

### 1. Truncated words
- **Detect:** any word cut mid-token, whether at a line end or mid-line — `HomeBrai` for
  `HomeBrain`, `Assistan` for `Assistant`, `repositor` for `repository`, `duri` for `during`,
  `chang` for `change` — and mashed/merged words where a boundary was lost (`wantrain`,
  `t mode`, `aon`). On the final emitted text this must be caught by reading it, not only by the
  deterministic script, which does not detect most mid-word cuts.
- **Repair:** restore the full word from context. If corruption is in the *visible* final
  output, STOP and re-render rather than emitting; do not report clean.

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

### 15. Skill-selection discipline
- **Applies to:** the optional `REQUIRED SKILLS` section (the downstream Layer 2 of
  `references/skill-selection.md`). This section is optional — its **absence is never a
  defect**. The concern is about a section that *is* present but is mis-scoped.
- **Detect (any of):**
  - **Too many** — more than three downstream skills listed.
  - **Skill dumping** — skills listed "for completeness" or "in case they help", or an
    enumeration that reads like a catalog rather than a task-specific shortlist.
  - **Irrelevant skills** — a listed skill has no bearing on the task's shape (for example a
    research or lookup skill in a pure single-file edit, or a skill with no statable one-line
    reason tied to this task).
  - **Companion leakage** — a builder companion skill
    (`engineering-skills:senior-prompt-engineer`, `superpowers:brainstorming`,
    `superpowers:verification-before-completion`) copied into the downstream prompt without an
    independent downstream reason.
  - **Empty heading** — a `REQUIRED SKILLS` heading with no skills under it.
- **Repair:** remove every skill that does not materially change execution quality, safety, or
  repo-convention adherence, keeping only those that do (prefer 0–3, per
  `references/skill-selection.md`). If nothing survives, delete the `REQUIRED SKILLS` section
  entirely rather than leaving an empty heading. This is a repair, not a flag — do not ask the
  user; prune to the materially useful set.

---

## Delivery integrity — relay/display corruption (post-emission)

Concerns 1-15 lint the prompt *content*. This concern is different: even a provably clean linted
file can be corrupted **after emission** by a display/relay/transport layer, so what the caller
*sees* in the transcript may not equal what was linted (mid-word cuts, mashed words, dropped
characters). The skill cannot lint or repair the transcript — that layer is outside its control —
so it must make the corruption *detectable* by the caller and never falsely claim the transcript
is clean.

- **Detect:** you cannot detect this by linting the draft. Assume the transcript may be corrupted
  for any output, and especially for long ones.
- **Mitigation (required):**
  - Treat the output **file** as the authoritative artifact. Report its **path, byte count, and
    SHA-256** so the caller can verify their copy by hashing it.
  - Claim cleanliness **only of the file identified by path + hash** — never of the visible
    transcript. If the caller's rendered copy does not match the SHA-256, the file is
    authoritative and the transcript was corrupted downstream.
  - For long outputs, **prefer delivering the file** and either omit the inline prompt text or
    label it explicitly as a non-authoritative convenience copy to be verified against the hash.

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
- known-term mid-word truncations (e.g. `HomeBrai` -> `HomeBrain`, `worktre` -> `worktree`) —
  a targeted backstop for concern 1 only; it does not catch arbitrary mid-word cuts or mashed
  words, so the Stage 4 visible-text read remains authoritative
- write-safety contradictions (the concern 7 sub-case, prompt mode only): flags
  research-only-plus-write, no-worktree-plus-write, no-main-edit-plus-write-without-worktree,
  and any explicit waiver of the worktree requirement. Write grants are detected from a range of
  phrasings (a "Write:" / "Write (optional" allowed-files bullet, "working tree only",
  "working-tree doc", "single/optional uncommitted working-tree file", "write exception")

Judgment-based, still handled by the checklist above (LLM inspection):
- broken commands (4), broken file paths (5), stale copied instructions (6) beyond marker
  words, contradictions (7) beyond the write-safety sub-case, ambiguous optional choices (9),
  skill-selection discipline (15) — the `REQUIRED SKILLS` section's relevance, count, and
  companion-leakage are all judgment calls the script does not check — and the parts of
  truncation and incomplete-sentence detection (1, 2) that need meaning.

The lint report should note which concerns were confirmed by `prompt_lint.py` and which were
verified by inspection.
