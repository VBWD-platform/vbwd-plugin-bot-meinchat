# bot-meinchat — importable artifacts

This directory holds the data-exchange **envelopes** this plugin owns. Each file
is a VBWD data-exchange envelope:

```json
{ "vbwd_export": "<entity_key>", "version": 1, "<entity_key>": [ ...rows ] }
```

Imported through the registered exchanger in upsert mode (natural key = `name`),
so a re-run is a no-op.

## Artifacts

| File | Entity | Purpose |
| --- | --- | --- |
| `bot-conversation-styles/default-style.json` | `bot_conversation_styles` | The shipped active `Default` bot-conversation style (the `--vbwd-botchat-*` palette the fe-user widget reads). Matches `style_seed.DEFAULT_STYLE_TOKENS` (single source). |

## Notes

The runtime demo seed (`populate_db.py`) ensures the default style through the
`seed_default_style` service (idempotent), not through this envelope; the
envelope is the **portable** artifact for moving / restoring the bot look across
instances via `flask data-exchange import bot_conversation_styles <file>` or the
generic Settings → Import/Export page (`settings` cluster).
