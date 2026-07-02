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

- **Allowed Files / Systems:** read-only access; no writes. Never grant a write, edit, create,
  or "single working-tree exception" here — a research-only prompt that permits any file write
  is self-contradictory (see **Write-safety consistency** below).
- **Forbidden Actions:** no file edits, no file creation, no mutating commands, no commits,
  no pushes, no service or state changes.
- **Verification:** cite sources and read-backs; confirm claims against the files or systems
  actually read.
- **Definition of Done:** findings delivered with evidence; no side effects. If a durable
  written note seems necessary, that is an implementation task, not research-only — switch the
  mode rather than carving out a write exception. The default deliverable is the answer in chat.
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
because it silently permits an unsafe edit. **A generated prompt must never combine a file
write with a stance that forbids the only safe way to make that write.** Concretely, the
prompt must not simultaneously:

- be `research-only` **and** allow any file write, file creation, edit, commit, or mutation;
- say "do not edit `main` directly" **and** allow a repository write without also requiring a
  worktree/branch process (a write in the `main` checkout *is* an edit to `main`);
- say "do not create branches or worktrees" **and** allow a repository write;
- present a "read-only" Allowed Files / Systems list **and** attach a write exception
  (a "single working-tree write", a "no-git write", etc.) — a working-tree write with no
  worktree still edits the checked-out branch.

These read as reasonable in isolation but cannot all hold: writing a file in the main checkout
edits `main`, and a working-tree-only carve-out does not change that.

### Repair policy (in order)

1. **Default for research/acquisition/decision tasks: chat-only, no file writes.** Deliver the
   recommendation or findings in the reply. Remove the write exception; keep the read-only
   Allowed Files / Systems list.
2. **If a durable written artifact is genuinely required, change the shape, not just the
   permission.** Switch the mode to `implementation`, add the `repo-safe` overlay, and require
   a worktree before any write (base-state check → `git worktree add …` → then write). The
   prompt then permits the write *because* it now mandates a safe process for it.
3. **If the user has not authorized a write, flag and ask — do not invent a writable
   deliverable.** State that the task as written is read-only and ask whether a durable file is
   wanted before switching modes.
4. **Never resolve the contradiction by keeping both.** A "single working-tree write exception"
   alongside "no worktree / no main edit" is never a valid output.
