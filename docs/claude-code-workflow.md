# Claude Code Workflow Guide

How to use the installed plugins, skills, and commands together. What each piece does, when to invoke it, and how they fit into a development workflow.

---

## Mental Model

There are three types of things installed:

- **Plugins** — installed via `claude plugin install`, managed by Claude Code independently of dotfiles. Available in every session globally.
- **Custom skills** — files in `claude/skills/`, deployed to `~/.claude/skills/` by `install.sh`. Available globally.
- **Custom commands** — files in `claude/commands/`, deployed to `~/.claude/commands/` by `install.sh`. Available globally.

Within these, there are two invocation modes:

- **You invoke** — slash commands you type (`/commit`, `/tech-debt`, `/ddup 123`)
- **Claude invokes** — Claude selects and uses these internally when they match the task. You trigger them by describing what you want in plain English.

---

## Plugins

### superpowers (`superpowers@claude-plugins-official`)

The orchestration layer. Provides structured workflows for planning, executing, and reviewing work.

**Skills you invoke:**

| Command | When to use |
|---|---|
| `/brainstorming` | Starting something new — explore the problem space, surface tradeoffs, generate options |
| `/write-plan` | After brainstorming — produces a structured implementation plan with tasks broken into steps |
| `/subagent-driven-development` | Executing a plan — dispatches a fresh subagent per task with spec + quality review after each |
| `/executing-plans` | Alternative to subagent-driven — for when you want to execute in a parallel session |
| `/systematic-debugging` | Stuck on a bug — structured root cause analysis |
| `/test-driven-development` | Starting a feature — TDD workflow with red/green/refactor cycle |
| `/using-git-worktrees` | Before a large feature — set up an isolated git worktree to avoid polluting main |
| `/finishing-a-development-branch` | End of a feature branch — final review, cleanup, PR preparation |

**Typical flow:**
```
/brainstorming → /write-plan → /subagent-driven-development → /finishing-a-development-branch
```

---

### engineering-skills (`engineering-skills@claude-code-skills`)

Specialist personas for different engineering domains. Claude invokes these internally when you describe a task that matches a specialty — you don't slash-command them directly.

**How to trigger:** Describe what you need in domain terms.

| Specialist | Trigger by asking for... |
|---|---|
| `senior-architect` | System design, architectural decisions, component boundaries, tech stack tradeoffs |
| `senior-backend` | API design, services, databases, performance, server-side patterns |
| `senior-frontend` | UI components, state management, accessibility, browser APIs |
| `senior-fullstack` | Features that span frontend and backend |
| `senior-ml-engineer` | Model training, inference pipelines, feature engineering, MLOps |
| `senior-data-engineer` | Data pipelines, ETL, warehouse design, Spark/Snowflake/Databricks |
| `senior-data-scientist` | Exploratory analysis, statistical modelling, experiment design |
| `senior-devops` | CI/CD pipelines, infrastructure, containerization, deployment |
| `senior-secops` | Security audits, threat modelling, auth/authz patterns |
| `senior-qa` | Test strategy, coverage analysis, edge case identification |
| `senior-security` | Security review of code changes |
| `code-reviewer` | Code review with specific quality criteria |
| `tech-stack-evaluator` | Comparing technology options for a given problem |
| `tdd-guide` | Test-driven development coaching and pattern guidance |

**Example:** "Review this C# service for performance issues" → `senior-backend` activates.

---

### commit-commands (`commit-commands@claude-plugins-official`)

Automates the git commit → push → PR flow.

| Command | What it does |
|---|---|
| `/commit` | Reads the diff, generates a conventional commit message, commits |
| `/commit-push-pr` | Commits + pushes + opens a PR with a generated title and description |
| `/clean_gone` | Removes local branches whose remote tracking branch is gone |

**When to use:** At the end of any coding session instead of writing commit messages manually.

---

### code-review (`code-review@claude-plugins-official`)

Automated PR review using 4 parallel agents, each with a different lens.

| Command | What it does |
|---|---|
| `/code-review` | Runs 4 agents in parallel: logic correctness, security, style/CLAUDE.md compliance, test coverage. Returns confidence-scored findings. |

**When to use:** Before merging any non-trivial change. Run it on the diff before creating a PR.

---

### pr-review-toolkit (`pr-review-toolkit@claude-plugins-official`)

Deeper, more specialized review than `code-review`. Six dedicated agents, each focused on one dimension.

| Agent | What it checks |
|---|---|
| `code-reviewer` | General review against project guidelines and best practices |
| `comment-analyzer` | Accuracy of code comments and docstrings — catches comment rot |
| `silent-failure-hunter` | Silent failures, swallowed exceptions, inappropriate fallbacks |
| `type-design-analyzer` | Quality of type definitions — encapsulation, invariant expression |
| `code-simplifier` | Complexity, redundancy, simpler alternatives |
| `pr-test-analyzer` | Test coverage quality and completeness |

**When to use:** `/review-pr` before marking a PR ready. More thorough than `/code-review` — use on significant changes.

**How it differs from code-review:** `code-review` is fast and broad (4 agents, general). `pr-review-toolkit` is deep and specific (6 agents, each expert in one dimension). Use both or choose based on change size.

---

### skill-creator (`skill-creator@claude-plugins-official`)

Helps build, improve, and benchmark Claude Code skills.

**When to use:**
- Building a new skill from scratch — ask "help me create a skill for X"
- Improving an existing skill — "improve this skill" + paste the SKILL.md
- Benchmarking a skill — runs the skill against test cases to validate it works

This is the foundation for Phases 2–5 of the skills expansion. Use it when `/skillify` produces a skill that needs refinement.

---

### claude-md-management (`claude-md-management@claude-plugins-official`)

Keeps CLAUDE.md files accurate and up to date.

| Command | What it does |
|---|---|
| `/revise-claude-md` | Captures learnings from the current session and proposes CLAUDE.md updates |
| `/claude-md-improver` | Audits a CLAUDE.md file — identifies gaps, outdated instructions, missing context |

**When to use:**
- `/revise-claude-md` — at the end of any session where you corrected Claude's behavior, established a new pattern, or made a decision that should be remembered
- `/claude-md-improver` — when setting up Claude Code in a new project, or after a period of heavy development when CLAUDE.md may have drifted

---

### claude-code-setup (`claude-code-setup@claude-plugins-official`)

Scans a codebase and recommends what Claude Code setup would be most useful for it.

**When to use:** Once, when first opening a project in Claude Code.

**What it produces:**
- Recommended hooks (PreToolUse, PostToolUse) for that project's patterns
- Suggested MCP servers that fit the tech stack
- Agent definitions appropriate for the domain
- Skills or commands that would help recurring workflows

**How to invoke:** Open Claude Code in the project directory and ask "run claude-code-setup" or "set up Claude Code for this project."

---

### security-guidance (`security-guidance@claude-plugins-official`)

Always-on PreToolUse hook. No invocation needed.

**What it does:** Intercepts every file edit and write, checks for security issues (injection, exposed secrets, insecure patterns), and warns before proceeding. Zero friction — it runs silently and only speaks up when it finds something.

---

## Custom Skills

### /skillify

**When:** End of a session where a repeatable workflow emerged.

Analyzes the conversation, identifies the repeatable steps, asks 4 clarifying questions, generates a `SKILL.md`, and saves it — either globally to dotfiles or to the current project.

**Output:** A new skill file ready to commit.

---

### /tech-debt

**When:** End of a feature or fix session.

Spawns 3 parallel agents (duplication hunter, dead code finder, redundancy reviewer). Presents findings, fixes approved items one at a time with test verification after each, commits if clean.

**Requires:** A project with a detectable test command (package.json, pyproject.toml, *.csproj, etc.).

---

### /verify-template

**When:** First time setting up Claude Code in a new project.

Scans the project for test, lint, and run commands. Confirms findings with you. Generates `.claude/skills/verify/SKILL.md` pre-filled with the discovered commands. You commit that file to the project repo.

**Output:** A project-specific `/verify` skill in `.claude/skills/verify/SKILL.md`.

---

## Custom Commands

### /ddup `<issue-number>`

**When:** You suspect a GitHub issue is a duplicate of an existing open issue.

Fetches the target issue and all open issues via `gh` CLI. Claude scores each for semantic similarity (0–100). Reports all candidates ≥ 40. Drafts a comment for the top match ≥ 70. Requires explicit "yes" before posting anything.

**Requires:** `gh` CLI authenticated (`gh auth login`).

---

## End-to-End Workflows

### Starting a new feature

```
1. /brainstorming          — explore the problem, surface tradeoffs
2. /write-plan             — produce a structured task plan
3. /subagent-driven-development  — execute plan with review loops
4. /commit-push-pr         — commit, push, open PR
5. /review-pr              — deep review before merging
6. /tech-debt              — cleanup after merge
7. /revise-claude-md       — capture any new patterns or decisions
```

### Setting up Claude Code in a new project

```
1. claude-code-setup       — scan repo, get recommendations
2. /verify-template        — generate project verify skill
3. /claude-md-improver     — audit or create CLAUDE.md for the project
```

### End of any session

```
/commit                    — if changes aren't committed yet
/tech-debt                 — if session produced significant code changes
/skillify                  — if a new repeatable workflow emerged
/revise-claude-md          — if you corrected behavior or made decisions
```

### Debugging a hard problem

```
/systematic-debugging      — structured root cause analysis
```

---

## Quick Reference

| I want to... | Use |
|---|---|
| Plan a feature | `/brainstorming` → `/write-plan` |
| Execute a plan | `/subagent-driven-development` |
| Commit my work | `/commit` or `/commit-push-pr` |
| Review before merging | `/code-review` or `/review-pr` |
| Clean up after a session | `/tech-debt` |
| Capture session learnings | `/revise-claude-md` |
| Create a skill from a workflow | `/skillify` |
| Check for duplicate issues | `/ddup <number>` |
| Set up a new project | `claude-code-setup` + `/verify-template` |
| Get specialist help | Describe the domain — engineering-skills activates |
| Debug a hard problem | `/systematic-debugging` |
| Improve a CLAUDE.md | `/claude-md-improver` |
