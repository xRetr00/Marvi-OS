# Marvi CLI Reference

Live sources when anything looks stale: `marvi --help`, `marvi <command> --help`,
https://github.com/xRetr00/Marvi-OS/docs/reference/cli-commands

### Global Flags

```
marvi [flags] [command]        (no subcommand = interactive chat)

  --version, -V             Show version
  -z, --oneshot PROMPT      One-shot: print ONLY the final response (for scripts/pipes)
  -m MODEL  --provider P    Model/provider override for this invocation
  -t, --toolsets LIST       Comma-separated toolsets for this invocation
  --resume, -r SESSION      Resume session by ID or title
  --continue, -c [NAME]     Resume by name, or most recent session
  --worktree, -w            Isolated git worktree mode (parallel agents)
  --skills, -s SKILL        Preload skills (comma-separate or repeat)
  --profile, -p NAME        Use a named profile
  --yolo                    Skip dangerous command approval
  --tui / --cli             Force the Ink TUI / classic REPL
  --ignore-rules            Skip AGENTS.md/SOUL.md/memory/skill injection
  --safe-mode               Disable ALL customizations (troubleshooting)
  --pass-session-id         Include session ID in system prompt
```

### Chat

```
marvi chat [flags]
  -q, --query TEXT          Single query, non-interactive
  --image PATH              Attach a local image to a single query
  -Q, --quiet               Suppress banner, spinner, tool previews
  --checkpoints             Enable filesystem checkpoints (/rollback)
  --max-turns N             Cap tool-calling iterations
  --source TAG              Session source tag (default: cli)
```
(plus the global flags above)

### Configuration

```
marvi setup [section]      Wizard (model|tts|terminal|gateway|tools|agent)
marvi model                Interactive model/provider picker
marvi fallback [add|remove|list]  Fallback provider chain
marvi config [show|edit|get|set|unset|path|env-path|check|migrate]
marvi login / logout       OAuth sign-in / clear stored auth
marvi doctor [--fix]       Check dependencies and config
marvi status [--all]       Component status
```

### Tools & Skills

```
marvi tools [list|enable NAME|disable NAME]   Per-platform toolsets (curses UI with no args)

marvi skills list|browse|search QUERY|inspect ID
marvi skills install ID    Hub identifier OR a direct https://…/SKILL.md URL
marvi skills config        Enable/disable skills per platform
marvi skills check|update|uninstall|publish PATH
marvi skills tap add REPO  Add a GitHub repo as a skill source
marvi bundles              Skill bundles (one /<name> alias loads several skills)
```

### MCP Servers

```
marvi mcp add NAME (--url or --command) | remove | list | test NAME
marvi mcp catalog | install NAME     Curated catalog install
marvi mcp configure NAME             Toggle tool selection
marvi mcp serve                      Run Marvi as an MCP server
```
Details (transport, tool discovery, catalog): `references/native-mcp.md`.

### Gateway (Messaging Platforms)

```
marvi gateway run|install|start|stop|restart|status|setup
```

20+ platforms: Telegram, Discord, Slack, WhatsApp (Baileys + Business Cloud API), iMessage (Photon — `marvi photon setup`), Signal, Email, SMS, Matrix, Mattermost, Teams, LINE, SimpleX, ntfy, Google Chat, Home Assistant, DingTalk, Feishu, WeCom, Weixin, API Server, Webhooks. Open WebUI connects via the API Server adapter. Most adapters ship under `plugins/platforms/`.
Docs: https://github.com/xRetr00/Marvi-OS/docs/user-guide/messaging/

### Sessions

```
marvi sessions list|browse|rename ID TITLE|delete ID|export OUT|prune|stats
```

### Cron / Webhooks

```
marvi cron list|create SCHED|edit ID|pause|resume|run ID|remove|status
    Schedules: '30m', 'every 2h', '0 9 * * *', ISO timestamp
marvi webhook subscribe NAME|list|remove NAME|test NAME
```
Webhook payloads/routes: `references/webhooks.md`.

### Profiles

```
marvi profile list|create NAME (--clone|--clone-all|--clone-from)|use|show|delete
marvi profile rename A B | alias NAME | export NAME | import FILE
```

### Credentials & Pools

```
marvi auth                 Interactive credential manager
marvi auth add [PROVIDER]  Add OAuth or API-key credential (nous, openai-codex, qwen-oauth, …)
marvi auth list|remove P IDX|reset PROVIDER|status
```
Multiple credentials per provider form a pool that rotates automatically and skips exhausted keys.

### Other

```
marvi desktop / gui        Native desktop app
marvi dashboard            Web admin panel + embedded chat (--stop / --status)
marvi proxy                OpenAI-compatible local proxy backed by an OAuth provider
marvi portal               Quick setup / sign in via Nous Portal
marvi kanban <verb>        Multi-agent work-queue board
marvi project              Named multi-folder workspaces
marvi skin list|use|set    Switch/tweak skins (see references/themes.md)
marvi pets <verb>          Pet mascots (see references/petdex.md)
marvi memory setup|status|off|reset   Memory provider
marvi secrets bitwarden|onepassword   External secret stores
marvi moa                  Mixture-of-Agents slots
marvi hooks / security / backup / import / checkpoints / console
marvi logs [-f] [errors]   View agent/error logs
marvi send                 One-off message through a gateway platform
marvi pairing / plugins / insights / journey / computer-use
marvi acp                  ACP server (IDE integration)
marvi completion bash|zsh|fish
marvi update / uninstall / claw migrate
```

Plugin- and provider-supplied subcommands (e.g. `marvi photon setup`) only appear once their plugin is installed/active.

### Where to Find Things

| Looking for... | Location |
|---|---|
| Config options | `marvi config edit` · [Configuration docs](https://github.com/xRetr00/Marvi-OS/docs/user-guide/configuration) |
| Tools / toolsets | `marvi tools list` · [Tools reference](https://github.com/xRetr00/Marvi-OS/docs/reference/tools-reference) |
| Skills catalog | `marvi skills browse` · [Skills catalog](https://github.com/xRetr00/Marvi-OS/docs/reference/skills-catalog) |
| Provider setup | `marvi model` · [Providers guide](https://github.com/xRetr00/Marvi-OS/docs/integrations/providers) |
| Env variables | `marvi config env-path` · [Env vars reference](https://github.com/xRetr00/Marvi-OS/docs/reference/environment-variables) |
| Gateway logs | `~/.marvi/logs/gateway.log` (or `marvi logs`) |
| Sessions | `marvi sessions browse` (reads state.db) |
