# Profiles — modes, overlays, and precedence

A profile shapes the twelve core sections with defaults and hard rules. Profiles compose
along two axes.

- **Mode (choose exactly one):** `research-only` or `implementation`.
- **Constraint overlays (stack any number):** `repo-safe`, `live-gated`, `homebrain`.

## Precedence

Low to high:

```
core < mode < repo-safe < live-gated < homebrain
```

When two layers set a conflicting rule, the higher-precedence layer wins. `homebrain`
implies `repo-safe` and `live-gated`, so selecting it pulls both in automatically.

---

## Mode: research-only

The agent investigates and reports; it does not change anything.

- **Allowed Files / Systems:** read-only access. **No repository writes, no exceptions** — not
  an "optional" write, not a "single working-tree doc", not an "uncommitted working-tree file".
  Any write, edit, or file creation permission means the prompt is **not** research-only (see
  **Write-safety consistency** below).
- **Forbidden Actions:** no file edits, no file creation, no mutating commands, no commits,
  no pushes, no service or state changes.
- **Verification:** cite sources and read-backs; confirm claims against the files or systems
  actually read.
- **Definition of Done:** findings delivered with evidence; no side effects. The default
  deliverable is the answer in chat. If a durable written note is wanted, that is **not** a
  research-only task — do not carve out a write exception; STOP and ask whether to switch to
  `implementation` + `repo-safe` with a worktree.
- **Expected Final Report:** the findings, the sources, and open questions.

## Mode: implementation

The agent makes changes within the allowed scope.

- **Allowed Files / Systems:** the explicit paths or globs the task permits.
- **Forbidden Actions:** no changes outside Allowed Files.
- **Required Steps:** make the change, then verify it.
- **Verification:** run the project's tests, build, or checks; include a changed-files check.
- **Definition of Done:** the change works, is verified with pasted evidence, and stays in
  scope.

---

## Overlay: repo-safe

For any change to a git repository. Adds to whichever mode is selected.

- **Required Steps (prepended):**
  1. Confirm local `main` equals `origin/main`. If not equal, STOP and report; do not branch.
  2. Work in an isolated git worktree under `.claude/worktrees/`; never edit `main` directly.
- **Forbidden Actions (added):**
  - Do not edit `main` directly.
  - Do not stage unrelated files; commit only what the task touches.
  - Do not push unless explicitly requested.
  - Do not add AI or Claude attribution to files, commits, or PRs.
- **Verification (added):** run `git status --porcelain` and confirm only in-scope files
  changed; run `git diff --stat` and confirm no out-of-scope files.
- **Stop Conditions (added):**
  - local `main` does not equal `origin/main` at the base check.
  - a change would fall outside Scope or Allowed Files.
  - before any `git add`, commit, or push — report verification and wait for approval.

## Overlay: live-gated

For systems with a live runtime component (host, service, API, resolver, exposure). The live
gate stays FREE (unclaimed) unless the task explicitly claims it: by default the generated
prompt grants no live access.

- **Forbidden Actions (added, default):**
  - No changes to any live host, service, API, resolver, or exposure.
  - No service restarts.
  - No new externally exposed tools or endpoints.
  - These hold unless the task explicitly authorizes a specific, scoped live action.
- **Stop Conditions (added):** if the task appears to require a live change that was not
  explicitly authorized, STOP and ask before acting.
- **When the task explicitly claims the gate:** permit only the specific live actions named,
  keep them narrowly scoped, and still require verification and a stop before each.

## Overlay: homebrain

For work on the HomeBrain stack. Implies `repo-safe` and `live-gated`, and adds the
HomeBrain rules verbatim.

- **Inputs / Required Reading (prepended, in order):**
  1. `docs/homebrain/ONBOARDING.md`
  2. `docs/homebrain/CHANGELOG.md`
  3. the relevant design or plan docs for the task
- **Forbidden Actions (added):**
  - Never edit `main` directly.
  - No live Home Assistant, host, API, service, resolver, or exposure changes unless
    explicitly authorized.
  - No `BACKLOG.md` edits unless explicitly authorized.
  - No stage, commit, or push unless separately approved.
  - No AI or Claude attribution.
- **Required Steps (added):**
  - Check that local `main` equals `origin/main` before branching; if not, STOP and report.
  - Keep docs, code, and runtime or config changes in separate commits where practical.
- **Verification (added):**
  - Always include a changed-files check.
  - Include a secret scan when writing docs or config-like content (no tokens, keys, or
    cookies committed).
- **Live gate:** keep it FREE unless the task explicitly claims it.

---

## Write-safety consistency (cross-cutting invariant)

This invariant applies to every profile and is the highest-value contradiction to catch,
because it silently permits an unsafe edit. It has bitten a real generated prompt (see
`examples/defects/research-optional-write-waiver-regression.md`), so the rules below are hard
and admit no "optional" or "single-file" loophole.

### Hard rules (no exceptions)

1. **`research-only` means zero repository writes.** No write, edit, file creation, or mutation
   — not even an "optional", "single", "uncommitted", or "working-tree-only" one. There is no
   such thing as a research-only prompt with a write exception.
2. **Any repository write means the prompt is not research-only.** If the task truly needs to
   write a file, the prompt must be `implementation` + `repo-safe`, not research-only with a
   carve-out.
3. **The `repo-safe` worktree requirement cannot be waived.** A "single working-tree doc", a
   "single optional uncommitted working-tree file", or an explicit "the worktree requirement was
   waived" is never acceptable. A write in the `main` checkout **is** an edit to `main`, whether
   or not it is committed; the only safe way to write is inside a worktree.
4. **A worktree does not rescue a research-only write.** Adding a `git worktree add` step to a
   `research-only` prompt does **not** make an optional doc write valid. The worktree makes an
   **implementation** write safe; it does not change the mode. `research-only` + worktree +
   write is just as forbidden as `research-only` + write — the fix is to change the **mode** to
   `implementation` + `repo-safe`, never to bolt a worktree onto a research-only prompt.
5. **Task authorization does not override profile safety rules.** "The task authorizes a write"
   or "authorized to create the doc" does not license a research-only or no-worktree write. An
   authorization only counts if it explicitly authorizes a write/live action **and** the prompt
   is represented as `implementation` + `repo-safe` (or a claimed `live-gated` action).

Concretely, a generated prompt must **never** simultaneously:

- be `research-only` **and** allow any file write, creation, edit, commit, or mutation — even if
  it also adds a worktree step (the worktree does not convert a research-only write into a valid
  one; change the mode to `implementation` instead);
- say "do not edit `main` directly" **and** allow a repository write without requiring a worktree;
- say "do not create branches or worktrees" (or waive the worktree requirement) **and** allow a
  repository write;
- present a "read-only" Allowed Files / Systems list **and** attach a write exception (an
  "optional" write, a "single working-tree doc", an "uncommitted working-tree file", etc.).

### Repair policy (in order)

1. **Default: chat-only, no file writes.** For research/acquisition/decision tasks, deliver the
   recommendation or findings in the reply. Remove any write exception; keep the Allowed Files /
   Systems list read-only.
2. **If a durable written artifact is requested, STOP and ask.** Do not silently invent a
   writable deliverable or keep a carve-out. Ask the user whether to switch the prompt to
   `implementation` + `repo-safe` with a worktree (base-state check → `git worktree add …` →
   then write). Only produce the writable shape once that switch is confirmed.
3. **Never allow an optional working-tree write under research-only or a no-worktree stance.**
   A "single working-tree write exception" alongside "no worktree / no main edit" — optional or
   not, committed or not — is never a valid output. **And never "fix" it by adding a worktree
   while keeping `research-only`** — `research-only` + worktree + optional write is not a valid
   final prompt. The only valid outputs are (a) chat-only/no writes, or (b) a mode switch to
   `implementation` + `repo-safe` + worktree, made only after the user confirms it.
