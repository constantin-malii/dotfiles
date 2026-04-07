---
name: verify-template
description: Generates a project-specific verify skill by scanning the codebase for test, lint, and run commands. Run once when setting up Claude Code in any new project. Saves output to .claude/skills/verify/SKILL.md in the current project.
---

# Verify Template

You are generating a project-specific verify skill. Your output is a `.claude/skills/verify/SKILL.md` file that gets committed to the current project — not to dotfiles.

## Step 1: Toolchain Discovery

Scan the current directory for toolchain indicators. Check in this order and use the first match for each category:

**Test command:**
1. `package.json` exists → read `scripts.test` field (e.g. `npm test`, `react-scripts test`, `vitest`)
2. `pyproject.toml` or `setup.py` exists → `pytest`
3. `*.csproj` or `*.sln` exists → `dotnet test`
4. `Cargo.toml` exists → `cargo test`
5. `go.mod` exists → `go test ./...`
6. `Makefile` with `test:` target → `make test`
7. CLAUDE.md has `## Testing` section → use whatever command is listed there
8. None found → leave as `# TODO: add test command`

**Lint command:**
1. `package.json` → read `scripts.lint` field; if absent but `.eslintrc*` or `eslint.config.*` exists → `npx eslint .`
2. `pyproject.toml` with `[tool.ruff]` → `ruff check .`; else if `[flake8]` in `setup.cfg` or `tox.ini` → `flake8`
3. `*.csproj` exists → `dotnet format --verify-no-changes`
4. `Cargo.toml` exists → `cargo clippy -- -D warnings`
5. `go.mod` exists → `go vet ./...`
6. CLAUDE.md has `## Linting` or `## Commands` section → use what's listed there
7. None found → leave as `# TODO: add lint command`

**Run/start command** (for development server or app entry point):
1. `package.json` → read `scripts.dev` or `scripts.start` field
2. `pyproject.toml` with `[tool.poetry.scripts]` → the first script entry
3. `Dockerfile` or `docker-compose.yml` exists → `docker compose up`
4. `Makefile` with `run:` or `start:` target → `make run`
5. None found → omit run command from the generated skill entirely

**Type check command** (optional — include only if found):
1. `tsconfig.json` exists → `npx tsc --noEmit`
2. `pyproject.toml` with `[tool.mypy]` or `mypy.ini` exists → `mypy .`
3. None found → omit

Record all discovered commands before proceeding.

## Step 2: Confirm With User

Present findings before generating anything:

```
Found in this project:
- Test:    <command or "not found">
- Lint:    <command or "not found">
- Run:     <command or "not found">
- Type check: <command or "omitting">

I'll generate .claude/skills/verify/SKILL.md with these commands filled in.

Shall I proceed? Any commands to change?
```

Wait for explicit confirmation. If the user corrects any command, use the corrected version.

## Step 3: Generate the Verify Skill

Write a complete `SKILL.md` using the discovered commands:

```
---
name: verify
description: Run the full verification suite for this project — tests, lint, and type checks. Use after any change to confirm nothing is broken.
---

# Verify

Run the full project verification suite.

## Commands

**Tests:**
```bash
<test command>
```
Expected: all tests passing, 0 failures

**Lint:**
```bash
<lint command>
```
Expected: no errors

<if type check found:>
**Type check:**
```bash
<type check command>
```
Expected: no errors
</if>

<if run command found:>
**Start (development):**
```bash
<run command>
```
</if>

## How to Use

Run all checks before committing:
```bash
<test command> && <lint command><if type check: && type check command>
```

If any check fails:
1. Read the error output
2. Fix the issue
3. Re-run the failing command to confirm it passes
4. Then run the full suite again

## Customization

Edit this file to add project-specific checks:
- Integration tests with a running service
- Database migration checks
- API contract tests
- Build steps that must pass before deploy
```

## Step 4: Save and Report

```bash
mkdir -p .claude/skills/verify
```

Write the generated content to `.claude/skills/verify/SKILL.md` in the current project directory.

Then tell the user:

```
Verify skill generated at .claude/skills/verify/SKILL.md

To commit it to this project:
  git add .claude/skills/verify/SKILL.md
  git commit -m "chore: add project verify skill"

To use it: /verify
```

**Important:** Do NOT commit to dotfiles. This file belongs to the current project, not to the dotfiles repo.
