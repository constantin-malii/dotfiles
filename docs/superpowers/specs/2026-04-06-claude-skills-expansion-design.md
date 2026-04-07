# Claude Skills Expansion Design

**Date:** 2026-04-06  
**Status:** Approved

## Goal

Expand the dotfiles Claude Code setup with marketplace plugins and custom-built skills/commands derived from the Anthropic team's internal workflow. Everything installable goes through the plugin system; everything custom-built lives in `claude/skills/` or `claude/commands/` and deploys via `install.sh`.

## Context

Current state:
- Plugins: superpowers, engineering-skills, finance-skills, c-level-skills
- Custom skills: /jira, /confluence, /azure-devops
- Infrastructure: `claude/agents/`, `claude/commands/`, `claude/skills/` wired into `install.sh`

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
2. Skill analyzes conversation: identifies repeatable steps, tools used, agents involved, permissions needed
3. Asks clarifying questions to confirm understanding
4. Generates a `SKILL.md` file and presents it for review
5. On approval, saves to the appropriate location

**Where it lives:** `claude/skills/skillify/SKILL.md` → deploys to `~/.claude/skills/skillify/`

**Reference:** Anthropic's internal Skillify source code (system prompt is in leaked source). Build from that as reference, not verbatim copy.

**Inputs:** Current session context  
**Outputs:** A complete `SKILL.md` file ready to commit to dotfiles

### Phase 3 — Tech Debt Skill (Custom Skill)

**What:** A generic end-of-session skill that finds duplicated code, redundant files, and accumulated tech debt across the codebase.

**Why:** Anthropic team runs this after every session. Keeps codebases clean incrementally rather than letting debt accumulate.

**How it works:**
1. User invokes `/tech-debt` at end of a session
2. Skill spawns multiple agents to analyze the codebase for duplication and redundancy
3. Reports findings with specific file references and duplication details
4. Creates a shared library/utility if appropriate, updates consumers
5. Runs linter and tests to verify nothing broke

**Where it lives:** `claude/skills/tech-debt/SKILL.md` → deploys to `~/.claude/skills/tech-debt/`

**Design constraint:** Generic enough to work across any project. Project-specific rules go in that project's CLAUDE.md, not in the skill itself.

### Phase 4 — DDUP Command (Custom Command)

**What:** A slash command that checks whether a GitHub issue is a duplicate of an existing open issue and comments on it if so.

**Why:** Useful for any project using GitHub Issues. Uses `gh` CLI already installed. Prevents duplicate issue noise.

**How it works:**
1. User invokes `/ddup <issue-number>` or `/ddup` (operates on current issue context)
2. Command fetches the issue title and body via `gh issue view`
3. Searches open issues for semantic similarity using `gh issue list` + analysis
4. If similarity ≥ 70%, comments on the issue explaining the match and linking the original
5. Always requires human confirmation before posting the comment
6. Reports findings even if below threshold (for human judgment)

**Where it lives:** `claude/commands/ddup.md` → deploys to `~/.claude/commands/ddup.md`

**Dependencies:** `gh` CLI (already installed and in verify.sh)

### Phase 5 — Verify Template (Custom Skill)

**What:** A starter template for a project-specific verify skill. Not a global skill — a dotfiles template that generates a tailored verify skill for any project.

**Why:** The Anthropic verify skill is highly project-specific (runs the app, tests, fixes failures). A generic version provides the structure; each project fills in the specifics.

**How it works:**
1. Template lives in dotfiles as `claude/skills/verify-template/SKILL.md`
2. When setting up a new project, run `/verify-template` to generate a project-specific verify skill
3. The generated skill scans the codebase (package.json, test commands, lint commands, run commands) and pre-fills the verification steps
4. Output is saved to `.claude/skills/verify/SKILL.md` in that project

**Where it lives:** `claude/skills/verify-template/SKILL.md` in dotfiles (template)  
Per-project output: `.claude/skills/verify/SKILL.md` (not committed to dotfiles)

## Architecture

```
dotfiles/
└── claude/
    ├── skills/
    │   ├── jira/           (existing)
    │   ├── confluence/     (existing)
    │   ├── azure-devops/   (existing)
    │   ├── skillify/       (Phase 2 — NEW)
    │   ├── tech-debt/      (Phase 3 — NEW)
    │   └── verify-template/ (Phase 5 — NEW)
    └── commands/
        └── ddup.md         (Phase 4 — NEW)

~/.claude/
├── skills/           (deployed by install.sh)
└── commands/         (deployed by install.sh)

Plugins (managed by Claude Code, not dotfiles):
  commit-commands, code-review, pr-review-toolkit,
  skill-creator, claude-md-management, claude-code-setup,
  security-guidance
```

## What Does NOT Change

- `install.sh` — already wires `claude/skills/` and `claude/commands/` to `~/.claude/`; no changes needed for Phases 2–5
- `verify.sh` — no new checks needed; skills/commands presence is implicitly verified by install
- Plugin installs — managed by Claude Code plugin system, not by install.sh

## Docs Updates (each phase)

Each phase updates:
- `README.md` — plugin table (Phase 1), new skills section (Phases 2–5)
- `CLAUDE.md` — bootstrap plugin install commands (Phase 1), task guide entries for using each skill (Phases 2–5)

## Success Criteria

- Phase 1: All 7 plugins installed and listed in `claude plugin list`; README and CLAUDE.md updated
- Phase 2: `/skillify` generates a valid SKILL.md file from a test session
- Phase 3: `/tech-debt` correctly identifies duplication in a test codebase
- Phase 4: `/ddup` correctly identifies a duplicate GitHub issue and drafts a comment
- Phase 5: `/verify-template` generates a project-specific verify skill with correct test/lint commands
