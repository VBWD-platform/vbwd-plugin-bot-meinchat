# bot-meinchat

The meinchat ↔ bot **bridge**: a second `IMessengerProvider` for the bot-base
stack that runs **in-process** inside meinchat (no webhook, no long-poll). It
proves the bot-base abstraction is provider-neutral — the same consumers (e.g.
`bot-meinchat-llm`) light up inside meinchat with zero consumer edit.

## What it does

- **In-process transport** — the bot's inbound edge is a meinchat
  `IPostSendHook` that ingests messages **only** in conversations where the
  configured bot user is a participant; every other human↔human chat is
  untouched. Outbound replies are posted back through the meinchat services.
- **Bot user provisioning** — the designated bot (`assistant`) is a real,
  findable meinchat user with role `BOT` plus a meinchat nickname, provisioned
  through services (never raw SQL) via `BotSenderProvisioner`. Any user can find
  it in nickname search and start a conversation; the bot answers there.
- **Automatic identity** — a meinchat sender is already an authenticated vbwd
  user, so there is no `/start` linking and no `bot_base_link` row.
- **Adaptive crypto** — `plain` when meinchat-plus is absent, `e2e_v1` when a
  real device directory is registered (selection only).
- **Conversation style** — ships and serves one default bot-conversation style
  (`GET /bot-conversation-style/active`) so the fe-user widget has an active
  look out of the box. The style is portable via the `bot_conversation_styles`
  data-exchange exchanger.

## Config keys (`config.json` / `admin-config.json`)

| Key | Default | Purpose |
| --- | --- | --- |
| `debug_mode` | `false` | Verbose debug logging. Disable in production. |
| `enabled` | `true` | Master switch for the in-process bridge. When off, no message is ever ingested. |
| `bot_user_email` | `bot-meinchat@bot.local` | Email of the designated bot user (real meinchat user with role `BOT`, provisioned automatically). Empty keeps the bridge inert. |
| `bot_nickname` | `assistant` | meinchat nickname the bot replies under and how users find it in search. |
| `bot_conversation_id` | `""` | Legacy optional single-conversation id. No longer the trigger — the bot answers in any conversation it participates in. Leave empty. |

## How it fits the bot stack

```
bot-base          transport-neutral bot core
  └─ bot-meinchat       this plugin: meinchat transport + bot identity + style
        └─ bot-meinchat-llm   the LLM consultant consumer
```

Declared plugin dependencies: `bot-base`, `meinchat`.
meinchat-plus is an **optional** runtime capability — detected via the
registered device-directory seam, never hard-imported.

## Demo data

`populate_db.py` is the idempotent seed: it ensures the one default conversation
style (through `seed_default_style`) and eagerly provisions the `assistant` bot
user + nickname (through `BotSenderProvisioner`) so a bot-widget that invites the
bot by nickname resolves out of the box. Both steps go through services.

## Importable artifacts

See [`docs/import/README.md`](docs/import/README.md) — ships a portable default
conversation-style envelope (`bot_conversation_styles`).

## Quality gate

```
cd vbwd-backend && bin/pre-commit-check.sh --plugin bot_meinchat --full
```
