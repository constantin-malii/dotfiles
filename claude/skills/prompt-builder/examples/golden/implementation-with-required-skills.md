# Golden example — implementation + repo-safe with an optional REQUIRED SKILLS section

**Rough intent:** "Reorganize the alias block in the shell config into categorized sections
and keep the CLAUDE.md alias documentation in sync."

**Profile:** mode `implementation`, overlay `repo-safe`.

**Why it is golden:** a genuinely multi-file, non-trivial task that materially benefits from
downstream skills, so it carries a bounded `REQUIRED SKILLS` section (two skills, placed right
after `ROLE`). It still satisfies the full twelve-section schema, the base-safety check, the
worktree requirement, changed-files verification, and the stop before commit. Contrast with
`defects/skill-dumping.md`, where a trivial task wrongly lists six skills.

```
ROLE
You are an implementation agent working in the dotfiles repo at D:\repos\dotfiles. Work like
a careful human developer who follows this repo's conventions.

REQUIRED SKILLS
- superpowers:subagent-driven-development — coordinate the multi-file change in disciplined,
  independently verifiable steps.
- superpowers:verification-before-completion — confirm the reorg and the docs match before
  claiming the work is done.

GOAL
Reorganize shell/.bash_profile aliases into categorized sections and update the CLAUDE.md
alias documentation to match, with no change in alias behavior.

CONTEXT
shell/.bash_profile is the source of truth; ~/.bash_profile is a deployed copy overwritten by
install.sh. The CLAUDE.md "Shell Config" section documents the alias layout, so a reorg must
keep the two in sync.

INPUTS / REQUIRED READING
1. shell/.bash_profile — the current alias block and its grouping.
2. CLAUDE.md — the "Shell Config" section that documents the alias layout.

SCOPE
In scope: regrouping existing alias lines under category headings in shell/.bash_profile, and
updating the matching CLAUDE.md documentation. Out of scope: adding, removing, or renaming any
alias; editing ~/.bash_profile; running install.sh.

ALLOWED FILES / SYSTEMS
- shell/.bash_profile
- CLAUDE.md
- Local git within the worktree.

FORBIDDEN ACTIONS
- Do not edit main directly; work in a git worktree under .claude/worktrees/.
- Do not change alias names or behavior; this is a pure reorganization.
- Do not edit ~/.bash_profile or any deployed copy.
- Do not stage unrelated files; commit only the reorg and its documentation.
- Do not push unless explicitly requested.
- Do not add AI or Claude attribution.

REQUIRED STEPS
1. Confirm local main equals origin/main. If not equal, STOP and report; do not branch.
2. Create a worktree: git worktree add .claude/worktrees/alias-reorg -b alias-reorg main
3. Regroup the alias lines under category headings in shell/.bash_profile without changing any
   alias definition.
4. Update the CLAUDE.md "Shell Config" documentation to match the new grouping.

VERIFICATION
- git -C <worktree> status --porcelain -> only shell/.bash_profile and CLAUDE.md changed.
- git -C <worktree> diff -- shell/.bash_profile -> shows only moved lines, no alias text
  changes (paste output).
- Confirm every alias present before the reorg is still present afterward.

STOP CONDITIONS
- local main does not equal origin/main at step 1 -> STOP and report.
- Any change would alter alias behavior or fall outside Allowed Files -> STOP and ask.
- Before any git add, commit, or push -> STOP; report verification; wait for approval.

DEFINITION OF DONE
- shell/.bash_profile aliases are grouped under category headings with behavior unchanged.
- CLAUDE.md documents the new grouping and matches the file.
- Verification pasted; only the two files changed; main untouched.

EXPECTED FINAL REPORT
- The diff of both files.
- Verification evidence (status --porcelain, diff, alias-parity check).
- Recommended next action (approve commit).
```

Lint report
- Profile: implementation + repo-safe
- Checked: all 15 concerns
- Repaired: nothing
- Flagged (needs your input): none
- Skill selection: REQUIRED SKILLS carries 2 downstream skills (within the 0–3 bound), both
  with a task-specific reason; no builder companion leakage (concern 15 clean).
- Mechanical checks: by inspection plus prompt_lint.py (clean)
