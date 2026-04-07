# Phase 3 — Tech Debt Skill

> **Part of:** [Claude Skills Expansion Master Plan](../2026-04-06-claude-skills-expansion.md)

**Goal:** Create `/tech-debt` — an end-of-session skill that finds duplicated code, dead code, and redundancy using multiple agents, then fixes approved items and verifies with the project's test/lint toolchain.

**Files:**
- Create: `claude/skills/tech-debt/SKILL.md`

**Depends on:** Phase 1

---

### Task 6: Create and deploy the Tech Debt skill

- [ ] **Step 1: Create `claude/skills/tech-debt/SKILL.md`**

```markdown
---
name: tech-debt
description: End-of-session cleanup skill. Finds duplicated code, dead code, and redundancy accumulated during the session. Run after completing any feature or fix to keep the codebase clean.
---

# Tech Debt Cleanup

You are performing an end-of-session tech debt cleanup. Your goal is to find and eliminate code duplication and redundancy introduced or exposed during this session.

## Step 1: Toolchain Discovery

Before doing anything else, determine how to run tests and linting. Check in this order and use the first match for each:

**Test command:**
1. `package.json` exists → read `scripts.test` field (e.g. `npm test`, `react-scripts test`)
2. `pyproject.toml` or `setup.py` exists → `pytest`
3. `*.csproj` or `*.sln` exists → `dotnet test`
4. `Cargo.toml` exists → `cargo test`
5. `go.mod` exists → `go test ./...`
6. `Makefile` with `test:` target → `make test`
7. CLAUDE.md has `## Testing` section → use whatever command is listed there
8. None found → skip verification at end and note it in the report

**Lint command:**
1. `package.json` → read `scripts.lint` field; if absent but `.eslintrc*` exists → `npx eslint .`
2. `pyproject.toml` with `[tool.ruff]` → `ruff check .`; else if `[flake8]` in `setup.cfg` → `flake8`
3. `*.csproj` exists → `dotnet format --verify-no-changes`
4. `Cargo.toml` exists → `cargo clippy -- -D warnings`
5. `go.mod` exists → `go vet ./...`
6. CLAUDE.md has `## Linting` or `## Commands` section → use what's listed there
7. None found → skip lint step and note it

Record both commands. You will run them in Step 4.

## Step 2: Parallel Codebase Analysis

Spawn three agents in parallel:

**Agent 1 — Duplication Hunter**

Find code that appears in multiple places and could be consolidated:
- Identical or near-identical functions (same logic, different variable names count)
- Repeated blocks of 5+ lines across multiple files
- Duplicated constants or configuration values
- Copy-pasted test setup or fixture code

For each duplication, report:
```
[file:line] duplicates [file:line]
Suggested fix: extract to <specific shared location>
```

**Agent 2 — Dead Code Finder**

Find code that is no longer referenced:
- Functions or methods defined but never called
- Unused imports
- Variables assigned but never read
- Files that are not imported or referenced anywhere in the project

For each item, report:
```
[file:line] — <reason it appears unused>
Safe to delete: yes / no (explain if no)
```

**Agent 3 — Redundancy Reviewer**

Find structural redundancy that adds complexity without value:
- Wrapper functions that only delegate to one other function with no transformation
- Abstractions with exactly one implementation that could be inlined
- Comments that restate exactly what the adjacent code does (noise, not signal)
- Overly complex constructs where a simpler built-in approach exists

For each item, report:
```
[file:line] — <description of redundancy>
Suggested fix: <specific action>
```

## Step 3: Present Report and Get Approval

Compile all findings:

```
## Tech Debt Report

### Duplications (extract to shared utility)
<agent 1 findings, or "None found">

### Dead Code (safe to remove)
<agent 2 findings, or "None found">

### Redundancy (simplify)
<agent 3 findings, or "None found">

### Recommended Actions (priority order)
1. <highest impact fix>
2. <second fix>
...
```

Ask: "Which of these would you like to fix now? (Say 'all', list numbers, or 'none' to skip)"

Wait for explicit response before proceeding.

## Step 4: Fix Approved Items

For each approved fix, one at a time:

1. Make the change
2. Run the test command discovered in Step 1
3. If tests fail: revert the change immediately (`git checkout -- <file>`), report the failure, skip to next item
4. If tests pass: move to next fix

Do not batch fixes. One change, one test run, then next.

## Step 5: Final Verification

Run both commands:

```bash
<test command>
<lint command>
```

Report:
```
Tests:  N passing, 0 failing
Linter: clean (or: N pre-existing issues, none introduced this session)
```

If clean, commit:
```bash
git add -A
git commit -m "refactor: tech debt cleanup — <one-line summary of what was fixed>"
```

If not clean, list the remaining issues and ask the user how to proceed. Do not commit with failing tests or new lint errors.
```

- [ ] **Step 2: Deploy and verify**

```bash
bash install.sh && bash verify.sh 2>&1 | grep "tech-debt"
```

Expected: `✅ tech-debt skill`

- [ ] **Step 3: Commit and push**

```bash
git add claude/skills/tech-debt/SKILL.md
git commit -m "feat: add tech-debt skill — end-of-session codebase cleanup with parallel agents"
git push
```
