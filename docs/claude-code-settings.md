# Claude Code Settings

Reference for `~/.claude/settings.json` — what each setting does and why it's configured this way.

Settings are managed directly in `~/.claude/settings.json` (not deployed by `install.sh`).

---

## Model

```json
"model": "claude-sonnet-4-6"
```

Sets the default model for all Claude Code sessions. Using the full model ID pins to a specific version rather than a family alias.

---

## Auto Updates

```json
"autoUpdatesChannel": "latest"
```

Tracks the `latest` release channel for Claude Code updates (as opposed to `stable`).

---

## Performance & Cost

```json
"env": {
  "DISABLE_PROMPT_CACHING": "true"
}
```

Disables prompt caching globally. Prompt caching can cause stale context to be reused across requests; disabling it ensures each request uses fresh context.

---

## Background Features (all disabled)

```json
"autoMemoryEnabled": false
```

Disables auto-memory — Claude will not automatically read from or write to the memory directory. Memory is managed manually.

```json
"autoDreamEnabled": false
```

Disables auto-dream — background memory consolidation that runs between sessions. Disabled to avoid unintended background writes.

```json
"proactive": {
  "autoEnable": false
}
```

Prevents autonomous background operation (proactive mode) from activating automatically at launch. Must be explicitly opted into per session.

---

## MCP Servers

`enableAllProjectMcpServers` is intentionally **not set** (defaults to `false`). Claude Code will prompt before enabling each MCP server rather than auto-approving all servers defined in `.mcp.json`.

---

## Status Line

```json
"statusLine": {
  "type": "command",
  "command": "bash /c/Users/Constantin/.claude/statusline-command.sh"
}
```

Custom status line powered by a shell script. See `claude/scripts/statusline-command.sh` in this repo.

---

## Plugins & Marketplaces

```json
"enabledPlugins": { ... },
"extraKnownMarketplaces": { ... }
```

Managed via `claude plugin install` / `claude plugin marketplace add`. See the Bootstrap section in `CLAUDE.md` for the full install sequence.
