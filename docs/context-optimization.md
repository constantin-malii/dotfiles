# Context & Rate Limit Optimization Guide

Strategies for managing Claude Code's context window, rate limits, and subagent costs effectively.

---

## Context Window Management

### How Auto-Compaction Works

- Claude Code reserves ~33K tokens (16.5% of window) as buffer
- Auto-compaction triggers at ~83.5% usage
- Clears older tool outputs first, then summarizes conversation
- Your prompts and key code snippets are preserved; detailed early instructions may be lost
- CLAUDE.md is reloaded every session and survives compaction (system-level injection)

### Compact Early, Not Late

- Compact at **60% capacity**, not 95% — the summary itself consumes tokens
- Use `/compact Focus on <what matters>` to control what survives
- Examples:
  - `/compact Focus on the API changes and test commands`
  - `/compact Preserve the list of modified files`
- Add to CLAUDE.md: `When compacting, always preserve the list of modified files and test commands`
- Compact at **natural breakpoints**: finishing a subtask, switching from research to implementation

### When to /clear and Start Fresh

- Every **15-20 messages** in long sessions
- After **two failed correction attempts** on the same issue
- When switching between unrelated tasks
- After several auto-compactions (performance degrades significantly)
- Use `/rename` before clearing so you can `/resume` later

### /btw — Zero-Cost Lookups

Answers appear in a dismissible overlay that **never enters conversation history**. Use for quick questions that don't need to persist in context.

---

## What to Keep vs Discard

| Persist to files (survives sessions) | Keep in context only (current session) |
|---|---|
| Plans, specs → `SPEC.md`, `task_plan.md` | Active implementation details for current task |
| Research findings → `findings.md` | Recent test output being debugged |
| Progress/session logs → `progress.md` | Current file diffs being reviewed |
| Conventions → CLAUDE.md | "What am I doing right now" state |
| Workflows → Skills (`.claude/skills/`) | |
| Per-session learnings → Memory (MEMORY.md) | |

**Rule:** If you'd need it in a future session, write it to disk. If it's only for the next 5 minutes, keep it in context.

### When to Save and Compact

- After completing a subtask — write findings to disk, then `/compact` or `/clear`
- Before switching from research to implementation mode
- When Claude starts repeating questions or contradicting earlier decisions
- At natural task breakpoints

---

## Minimizing Context Consumption

### File Reading

- **Targeted reads over full file reads**: "check the verifyUser function in auth.js" beats "here's my repo, find the bug"
- Use `@filename` to point at specific files instead of letting Claude explore freely
- Reference specific files by path rather than asking Claude to search

### Tool Calls

- Every file read, command output, and tool result enters the context window
- MCP servers can be expensive: one developer documented **67K tokens consumed** from 4 MCP servers before typing a single prompt
- CLI tools (gh, aws, gcloud) are more context-efficient than MCP servers
- Run `/context` to audit what's consuming space; `/mcp` to check per-server costs
- Disable unused MCP servers before they eat context

### CLAUDE.md

- Gets injected into **every single request** — keep it **under 200 lines / 2,000 tokens**
- Only include things Claude cannot figure out by reading code
- Move specialized workflow instructions into **skills** (loaded on-demand) rather than bloating CLAUDE.md
- For skills you invoke manually, set `disable-model-invocation: true` to keep descriptions out of context

### Hooks for Preprocessing

- Use hooks to filter data before Claude sees it
- Instead of Claude reading a 10,000-line log, a hook can grep for ERROR and return only matching lines — reducing context from tens of thousands of tokens to hundreds

---

## Subagent Context Patterns

### How Context Isolation Works

- Each subagent runs in its **own fresh context window**
- The only channel from parent to subagent is the prompt string
- Intermediate tool calls and file reads **stay inside the subagent** — don't pollute the parent
- Parent receives only a **concise summary** back, not every file the subagent read
- Subagents **cannot spawn other subagents** (no infinite nesting)

### Built-in Subagent Types

| Type | Model | Tools | Use for |
|---|---|---|---|
| Explore | Haiku (fast, cheap) | Read-only | File search, codebase exploration |
| Plan | Inherits parent | Read-only | Research during plan mode |
| General-purpose | Inherits parent | All tools | Complex multi-step tasks |

### Cost Implications

- **All subagent tokens count against your rate limit** — they are NOT free
- Parallel subagents accelerate token consumption (5 parallel agents can hit limits in ~15 min vs ~30 min sequential)
- Route simple tasks to **Haiku subagents** (`model: haiku`) — 5x cheaper than Opus
- Keep spawn prompts focused and specific

### When to Use Subagents

- **Research/investigation** that would read many files — keeps main context clean
- **Verification after implementation** — fresh context means no bias toward code just written
- **Verbose operations**: running tests, fetching docs, processing logs
- **The writer/reviewer pattern**: one session/subagent implements, another reviews with fresh eyes

---

## Rate Limit Optimization

### The Rolling 5-Hour Window

- Token-based, not request-based — large responses consume more
- Cumulative tokens from the past 5 hours determine your limit
- Old usage drops off continuously as requests age past 5 hours
- No fixed reset time — it's a rolling window
- If exhausted early, you wait for oldest requests to age out

### Model Choice Matters

| Model | Relative cost | Use for |
|---|---|---|
| Haiku | 1x (cheapest) | Quick lookups, formatting, subagent exploration |
| Sonnet | ~3x | Most development work, coding, debugging |
| Opus | ~5x | Complex architecture, design decisions, reviews |

- Use `/model` to switch mid-session based on task complexity
- `/fast` mode uses the same model with faster output — does NOT switch to a cheaper model

### Reduce Thinking Token Usage

- Extended thinking is enabled by default and can consume tens of thousands of tokens per request
- Use `/effort` to lower effort level for simpler tasks
- Set `MAX_THINKING_TOKENS=8000` for mechanical tasks
- Disable thinking entirely in `/config` for trivial operations

### Practical Strategies

1. **Batch edits** — one comprehensive diff request burns fewer tokens than iterative "please refine" follow-ups
2. **Time your window** — start a brief request 3-4 hours before intended heavy work session
3. **Monitor continuously** — configure status line to show context % and rate usage
4. **Task-scoped sessions** — one session per defined task, not one session for everything
5. **Use `/cost`** to check token usage at any time

---

## Power User Patterns

### Plan-Then-Execute (Most Effective)

1. Session A: Research and plan → save spec to `SPEC.md` or `task_plan.md`
2. `/clear` or start new session
3. Session B: Implement from the spec with clean context

The implementation session has full context focused on execution + a written spec to reference.

### Planning-with-Files (Persistent Working Memory)

Three files as "disk-backed working memory":
- `task_plan.md` — phases, milestones, current state
- `findings.md` — research discoveries, decisions made
- `progress.md` — session logs, errors encountered

**Session handoff**: Before ending, update progress files. New session reads them to recover full state in seconds. Context Window = RAM (volatile, limited); Filesystem = Disk (persistent, unlimited).

### Writer/Reviewer Split

- Session A implements a feature
- Session B (fresh context, no bias) reviews it
- Similarly: one session writes tests, another writes code to pass them

### The 80/20 Rule

- Stop complex multi-file tasks at **80% context capacity**
- Save final 20% for lightweight work (committing, quick fixes)
- Every 30 minutes in long sessions, ask Claude to review changes and confirm patterns

### One Task Per Session

- Community consensus: **short, focused sessions beat long marathons**
- Long sessions lead to: inconsistent code, repeated questions, lost decisions, breaking changes
- Commit frequently so you can pick up in a new session
- Use `/rename` to label sessions for easy `/resume`

---

## Quick Reference

| I want to... | Do this |
|---|---|
| Free lookup without context cost | `/btw <question>` |
| Check what's eating context | `/context` |
| Check MCP server costs | `/mcp` |
| Check token usage and cost | `/cost` |
| Compact with focus | `/compact Focus on <topic>` |
| Switch to cheaper model | `/model sonnet` or `/model haiku` |
| Lower thinking effort | `/effort` or `MAX_THINKING_TOKENS=8000` |
| Save session for later | `/rename <name>` then `/clear` |
| Resume a saved session | `/resume` |
| Keep research out of main context | Use subagents (Agent tool with Explore type) |
