# bot-meinchat — overview

`bot-meinchat` bridges the provider-neutral bot core (`bot-base`) to the
in-process meinchat messenger. It is the evidence that the bot-base seam is
transport-agnostic: a consumer written against bot-base (e.g. the LLM
consultant) works over meinchat with no consumer change.

## Inbound edge

The bridge registers a meinchat `IPostSendHook`. On every posted message it
checks whether the configured **bot user** is a participant of that
conversation; if so the message is ingested and dispatched through bot-base's
command dispatcher, otherwise it is ignored. This scoping means no human↔human
chat is ever read by the bot.

## Identity

A meinchat sender is already an authenticated vbwd user, so the bot reuses that
identity directly — there is no one-time link token flow as with external
adapters (Telegram). The bot itself is a provisioned `BOT`-role meinchat user
(`assistant`) so guests can discover it in nickname search.

## Conversation style

The plugin owns the bot-conversation **style** (the widget's
`--vbwd-botchat-*` palette). It seeds one active `Default` style and serves the
active style at `GET /bot-conversation-style/active`. The style round-trips
between instances through the `bot_conversation_styles` data-exchange exchanger
(see [`import/README.md`](import/README.md)).

## Crypto

`plain` by default; `e2e_v1` is selected only when a real meinchat-plus device
directory is registered. meinchat-plus is detected through the device-directory
seam and never hard-imported.
