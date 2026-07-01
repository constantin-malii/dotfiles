# Lint Checklist — mandatory pass before output

Run every rule below against the assembled draft in Stage 3. For each concern: apply the
detect signal; if it fires, apply the repair action. Record checked / repaired / flagged for
the lint report.

Two outcomes are possible per concern:
- **repair** — fix it inline and note it.
- **flag** — a required input is genuinely unknown; note it and ask the user. Do not guess.

The generated prompt must pass all rules before it is shown (dogfooding).

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

### 8. Unsafe git or environment rules
- **Detect:** branching or committing without a base-state check; editing `main` directly;
  destructive commands without a guard; assuming a branch or base that was not verified.
- **Repair:** insert the base-safety check (local `main` equals `origin/main`, else STOP) and
  the worktree requirement from the repo-safe overlay.

### 9. Ambiguous optional choices
- **Detect:** an instruction offering options without a decision rule ("optionally do X",
  "you may want to Y") that leaves the agent to guess.
- **Repair:** make the choice explicit, or state the exact condition under which each option
  applies.

### 10. Missing allowed-file scope
- **Detect:** the Allowed Files / Systems section is absent or empty.
- **Repair:** fill it from the profile and scope; **flag** and ask only if it cannot be
  reasonably inferred.

### 11. Missing forbidden actions
- **Detect:** the Forbidden Actions section is absent or empty, or omits the active profile's
  hard rules.
- **Repair:** add the profile's forbidden actions.

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

Structural concerns (7–14) are explicit section checks and are expected to be caught
reliably. Mechanical concerns (1–6) rely on inspection here and are hardened toward reliable
detection once the deterministic `prompt_lint.py` script lands (Increment 3). Until then, the
lint report should state that mechanical checks were performed by inspection.
