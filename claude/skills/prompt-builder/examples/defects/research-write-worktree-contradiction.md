# Defect example — research-only prompt that permits a write while forbidding worktrees (REAL, trimmed)

**Source:** REAL (trimmed). Produced by an earlier prompt-builder run for a Z-Wave adapter
acquisition-check task. The prompt was mostly a research/acquisition-decision task, yet it
allowed an optional file write while also forbidding a worktree and any `main` edit — an
internal contradiction, because writing the file in the main checkout *is* an edit to `main`.

**Lint concerns demonstrated:**
- 7 contradictions (write-safety sub-case — the governing concern)
- 8 unsafe git or environment rules (a repository write with no safe process)
- 10 missing/invalid allowed-file scope (a "read-only" list carrying a write exception)
- 11 forbidden actions conflict with allowed actions (no worktree / no main edit vs. an allowed write)

**Bad excerpt:**

```
ROLE
You are a research agent evaluating a Z-Wave adapter acquisition. You investigate public
sources and the local docs, then recommend whether to acquire.

ALLOWED FILES / SYSTEMS
- Read-only: all files under docs/homebrain/, and public vendor/retailer web pages.
- Write (single deliberate exception to read-only, working tree only, no git actions):
  docs/homebrain/2026-07-01-rq-06-zwa-2-acquisition-check.md — only if a written decision note
  is warranted; otherwise deliver the recommendation in chat.

FORBIDDEN ACTIONS
- Do not stage, commit, or push anything unless separately approved.
- Do not edit main directly; do not create branches or worktrees for this task.
- Do not edit any file other than the single decision-note doc named in Allowed Files.
```

**Expected verdict:** repair (default), or flag if it is unclear whether a durable file was
authorized.

**Expected repair summary:**
- This is a contradiction (concern 7, write-safety sub-case): the prompt is framed research-only
  and read-only, forbids `main` edits, and forbids worktrees, yet grants a working-tree write.
  A working-tree write in the main checkout edits `main`; the "single exception / no git actions"
  carve-out does not make it safe. It also trips concerns 8, 10, and 11.
- **Default repair (chat-only):** since this is a research/acquisition-decision task, remove the
  write exception and keep the Allowed Files / Systems list read-only. Deliver the recommendation
  in chat. This is the preferred resolution for research/acquisition/decision tasks.
- **If a durable decision note is genuinely required:** change the shape, not just the
  permission. Switch the mode to `implementation`, add the `repo-safe` overlay, and require a
  worktree before the write: base-state check (local `main` equals `origin/main`, else STOP),
  `git worktree add .claude/worktrees/<name> -b <branch> origin/main`, then write the doc under
  the worktree. Keep the "no commit/push without approval" stop.
- **If no write was authorized:** flag and ask whether a durable file is wanted before switching
  modes — do not invent a writable deliverable.
- Never keep both: a "single working-tree write exception" alongside "no worktree / no main edit"
  is never a valid output.

**Deterministic detection:** `prompt_lint.py --prompt` flags this via the write-safety checks —
research-only-plus-write (the "Write (…)" grant with a "research agent" role) and
no-worktree-plus-write ("do not create … worktrees" with the same write grant).
