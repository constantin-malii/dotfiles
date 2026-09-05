# Golden example — implementation mode + repo-safe overlay

**Rough intent:** "Add a `gs` alias for `git status` to the shell config."

**Profile:** mode `implementation`, overlay `repo-safe`.

**Why it is golden:** worktree-based, base-safety check first, explicit allowed file,
changed-files verification, stop before commit.

```
ROLE
You are an implementation agent working in the dotfiles repo at D:\repos\dotfiles. Work like
a careful human developer who follows this repo's conventions.

GOAL
Add a `gs` alias for `git status` to the committed shell config.

CONTEXT
shell/.bash_profile is the source of truth; ~/.bash_profile is a deployed copy overwritten by
install.sh. Aliases are grouped by category in shell/.bash_profile.

INPUTS / REQUIRED READING
1. shell/.bash_profile — the alias sections and where a git alias belongs.
2. CLAUDE.md — the "Shell Config" rules (edit shell/, never ~/).

SCOPE
In scope: adding one alias line to shell/.bash_profile in the git alias section. Out of
scope: editing ~/.bash_profile, adding unrelated aliases, running install.sh.

ALLOWED FILES / SYSTEMS
- shell/.bash_profile
- Local git within the worktree.

FORBIDDEN ACTIONS
- Do not edit main directly; work in a git worktree under .claude/worktrees/.
- Do not edit ~/.bash_profile or any deployed copy.
- Do not stage unrelated files; commit only the alias change.
- Do not push unless explicitly requested.
- Do not add AI or Claude attribution.

REQUIRED STEPS
1. Confirm local main equals origin/main. If not equal, STOP and report; do not branch.
2. Create a worktree: git worktree add .claude/worktrees/gs-alias -b gs-alias main
3. Add `alias gs='git status'` to the git alias section of shell/.bash_profile.

VERIFICATION
- git -C <worktree> status --porcelain -> only shell/.bash_profile changed (paste output).
- git -C <worktree> diff -- shell/.bash_profile -> shows exactly the one added line.

STOP CONDITIONS
- local main does not equal origin/main at step 1 -> STOP and report.
- Any change would fall outside Scope or Allowed Files -> STOP and ask.
- Before any git add, commit, or push -> STOP; report verification; wait for approval.

DEFINITION OF DONE
- shell/.bash_profile contains the new alias in the correct section.
- Verification pasted; only the one file changed; main untouched.

EXPECTED FINAL REPORT
- The diff of the added line.
- Verification evidence (status --porcelain, diff).
- Recommended next action (approve commit).
```

Lint report
- Profile: implementation + repo-safe
- Checked: all 15 concerns
- Repaired: nothing
- Flagged (needs your input): none
- Mechanical checks: by inspection (deterministic script arrives in Increment 3)
