# Claude Skills Expansion Design

**Date:** 2026-04-06  
**Status:** Approved (rev 2 — post code review fixes)

## Goal

Expand the dotfiles Claude Code setup with marketplace plugins and custom-built skills/commands derived from the Anthropic team's internal workflow. Everything installable goes through the plugin system; everything custom-built lives in `claude/skills/` or `claude/commands/` and deploys via `install.sh`.

## Context

Current state:
- Plugins: superpowers, engineering-skills, finance-skills, c-level-skills
- Custom skills: /jira, /confluence, /azure-devops
- Infrastructure: `claude/agents/`, `claude/commands/`, `claude/skills/` wired into `install.sh`

## Invocation Model (Resolved)

In Claude Code, both `~/.claude/skills/` and `~/.claude/commands/` are user-invocable via slash commands. The distinction:

- **`~/.claude/skills/<name>/SKILL.md`** — structured skill with metadata frontmatter; can be invoked by Claude internally (via the Skill tool) OR by the user via `/name`. Use for complex multi-step workflows.
- **`~/.claude/commands/<name>.md`** — simple command invoked by the user via `/name`. Use for single-purpose, user-triggered actions.

Applied to this project:
- Skillify → `claude/skills/skillify/` — complex workflow, Claude may invoke internally during sessions
- Tech Debt → `claude/skills/tech-debt/` — complex multi-agent workflow
- Verify Template → `claude/skills/verify-template/` — complex, generates output files
- DDUP → `claude/commands/ddup.md` — single-purpose, always user-triggered

All four are user-invocable via slash commands.

## What We Are Building

### Phase 1 — Marketplace Plugin Installs

Install 7 plugins. No code written. Update `CLAUDE.md` bootstrap and `README.md` plugin table.

| Plugin | Provides | Why |
|--------|----------|-----|
| `commit-commands` | `/commit`, `/push`, `/pr` slash commands | Eliminates repetitive git steps in every session |
| `code-review` | `/code-review` — 4 parallel agents, confidence-scored | Automated PR review against CLAUDE.md + logic + security + style |
| `pr-review-toolkit` | 6 specialized review agents | Deeper per-dimension analysis: comments, tests, errors, types, simplification |
| `skill-creator` | Skill creation, improvement, benchmarking | Foundation for Phases 2–5; needed before building custom skills |
| `claude-md-management` | `claude-md-improver` skill + `/revise-claude-md` command | Keeps CLAUDE.md files accurate; captures session learnings automatically |
| `claude-code-setup` | Codebase scan → recommends hooks/skills/MCPs per project | Run once per new repo to get tailored recommendations |
| `security-guidance` | PreToolUse hook — warns on Edit/Write with security context | Always-on safety net; zero friction |

**Not installing:** frontend-design (no frontend work), code-simplifier (redundant with pr-review-toolkit), feature-dev (superpowers covers this), ralph-loop (experimental), hookify (deferred — install when hooks are needed).

### Phase 2 — Skillify (Custom Skill)

**What:** A skill that analyzes a completed session and converts the workflow into a reusable, saved skill file.

**Why first:** Highest leverage. Every workflow refined in conversation becomes a skill automatically. Accelerates Phases 3–5 and all future skill creation.

**How it works:**
1. User invokes `/skillify` at end of a session
2. Skill analyzes the session: identifies repeatable steps, tools used, agents involved, permissions needed
3. Asks clarifying questions to confirm understanding
4. Generates a `SKILL.md` file and presents it for review
5. On approval, saves to the appropriate location (`claude/skills/<name>/` in dotfiles, or `.claude/skills/<name>/` in the current project)

**Where it lives:** `claude/skills/skillify/SKILL.md` → deploys to `~/.claude/skills/skillify/`

**Reference:** Built from first principles based on the described behavior of Anthropic's internal Skillify (the system prompt structure has been discussed publicly in the community — this is a clean-room implementation inspired by that description, not a copy of any source).

**Inputs:** Current session context  
**Outputs:** A complete `SKILL.md` file ready to commit

### Phase 3 — Tech Debt Skill (Custom Skill)

**What:** A generic end-of-session skill that finds duplicated code, redundant files, and accumulated tech debt across the codebase.

**Why:** Anthropic team runs this after every session. Keeps codebases clean incrementally rather than letting debt accumulate.

**How it works:**
1. User invokes `/tech-debt` at end of a session
2. Skill spawns multiple agents to analyze the codebase for duplication and redundancy
3. Reports findings with specific file references and duplication details
4. Creates a shared library/utility if appropriate, updates consumers
5. Runs linter and tests to verify nothing broke

**Toolchain discovery:** The skill scans for toolchain indicators in this order before running any verification:
- `package.json` → `npm test`, `npm run lint` (or scripts.lint/test fields)
- `pyproject.toml` / `setup.py` → `pytest`, `ruff check`
- `*.csproj` / `*.sln` → `dotnet test`, `dotnet format`
- `Cargo.toml` → `cargo test`, `cargo clippy`
- `go.mod` → `go test ./...`, `go vet`
- Falls back to CLAUDE.md `## Testing` section if present
- If none found: reports findings only, skips verification step with a note

**Where it lives:** `claude/skills/tech-debt/SKILL.md` → deploys to `~/.claude/skills/tech-debt/`

**Design constraint:** Generic enough to work across any project. Project-specific rules go in that project's CLAUDE.md, not in the skill itself.

### Phase 4 — DDUP Command (Custom Command)

**What:** A slash command that checks whether a GitHub issue is a duplicate of an existing open issue and comments on it if so.

**Why:** Useful for any project using GitHub Issues. Uses `gh` CLI already installed. Prevents duplicate issue noise.

**Similarity algorithm:** Claude itself performs the comparison — no external embeddings or string matching libraries. The process:
1. Fetch target issue via `gh issue view <number> --json title,body`
2. Fetch all open issues via `gh issue list --json number,title,body --limit 200`
3. Claude reads both and judges semantic similarity on a 0–100 scale, considering: same root cause, same feature request, same bug symptom (even if described differently)
4. "70% threshold" means Claude's confidence score ≥ 70 that the issues describe the same underlying problem
5. Claude explains its reasoning for any match found

**How it works:**
1. User invokes `/ddup <issue-number>`
2. Fetches target issue and all open issues via `gh`
3. Claude compares semantically and scores matches
4. Presents findings (matches and near-matches) with reasoning
5. If match found ≥ 70: drafts a comment explaining the duplicate and linking the original
6. Requires explicit user confirmation before posting via `gh issue comment`

**Where it lives:** `claude/commands/ddup.md` → deploys to `~/.claude/commands/ddup.md`

**Dependencies:** `gh` CLI (already installed and verified in verify.sh)

### Phase 5 — Verify Template (Custom Skill)

**What:** A starter template for a project-specific verify skill. Not a global skill — a dotfiles template that generates a tailored verify skill for any project.

**Why:** The Anthropic verify skill is highly project-specific (runs the app, tests, fixes failures). A generic version provides the structure; each project fills in the specifics.

**How it works:**
1. Template lives in dotfiles as `claude/skills/verify-template/SKILL.md`
2. When setting up a new project, user runs `/verify-template`
3. Skill scans the codebase using the same toolchain discovery as Phase 3 (package.json, pyproject.toml, *.csproj, etc.)
4. Pre-fills a verify skill with discovered test commands, lint commands, and run commands
5. Saves the generated skill to `.claude/skills/verify/SKILL.md` in the current project (not in dotfiles)

**Where it lives:** `claude/skills/verify-template/SKILL.md` in dotfiles (the generator)
Per-project output: `.claude/skills/verify/SKILL.md` (committed to that project, not to dotfiles)

## What Changes in Each Supporting File

### verify.sh

**Fix required:** The skill verification loop at line 157 is hardcoded:
```bash
for skill in jira confluence azure-devops; do
```

This must be generalized to dynamically scan the deployed skills directory so new skills (skillify, tech-debt, verify-template) are verified automatically:
```bash
# Verify all skills present in repo are deployed
for skill_dir in "$REPO_DIR/claude/skills"/*/; do
    skill_name=$(basename "$skill_dir")
    if [[ -d "$CLAUDE_DIR/skills/$skill_name" ]]; then
        ok "$skill_name skill"
    else
        fail "$skill_name skill not found in ~/.claude/skills/"
    fi
done
```

This change happens in **Phase 1** (before any new skills exist) so the fix is in place before it's needed.

### install.sh

No changes needed. Lines 132–133 already use `rsync -a --delete` on the full `claude/skills/` directory — new skill subdirectories deploy automatically.

### README.md and CLAUDE.md

Updated in each phase:
- Phase 1: Plugin table updated with all 7 new plugins + bootstrap install commands
- Phases 2–5: New skills/commands documented with usage examples

## Architecture

```
dotfiles/
└── claude/
    ├── skills/
    │   ├── jira/              (existing)
    │   ├── confluence/        (existing)
    │   ├── azure-devops/      (existing)
    │   ├── skillify/          (Phase 2 — NEW)
    │   ├── tech-debt/         (Phase 3 — NEW)
    │   └── verify-template/   (Phase 5 — NEW)
    └── commands/
        └── ddup.md            (Phase 4 — NEW)

~/.claude/
├── skills/     (deployed by install.sh rsync)
└── commands/   (deployed by install.sh rsync)

Plugins (managed by Claude Code plugin system, not dotfiles):
  commit-commands, code-review, pr-review-toolkit,
  skill-creator, claude-md-management, claude-code-setup,
  security-guidance
```

## Success Criteria

- **Phase 1:** All 7 plugins installed; `claude plugin list` confirms; README and CLAUDE.md updated; verify.sh skill loop generalized
- **Phase 2:** `/skillify` generates a valid SKILL.md from a test session description; file is committable
- **Phase 3:** `/tech-debt` detects duplication in a test codebase; correctly discovers toolchain; runs verification
- **Phase 4:** `/ddup` fetches issues via `gh`, identifies a seeded duplicate with correct reasoning, drafts comment, requires confirmation before posting
- **Phase 5:** `/verify-template` scans a project, discovers test/lint commands, writes `.claude/skills/verify/SKILL.md` with correct content
