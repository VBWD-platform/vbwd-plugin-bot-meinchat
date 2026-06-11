"""Unit specs for the bot-meinchat plugin config (no DB, no app context).

The refinement: the bot is the designated meinchat user named by
``bot_user_email``. An empty / missing ``bot_user_email`` keeps the bridge inert
(no crash, no provisioning) — the no-bot-designated safety path.
"""
from plugins.bot_meinchat import BotMeinchatPlugin, DEFAULT_CONFIG


def test_default_config_designates_the_bot_by_email():
    assert DEFAULT_CONFIG["bot_user_email"] == "bot-meinchat@bot.local"
    assert DEFAULT_CONFIG["bot_nickname"] == "assistant"
    # Legacy single-conversation key is retained but empty (no longer a trigger).
    assert DEFAULT_CONFIG["bot_conversation_id"] == ""


def test_resolve_bot_user_id_is_inert_when_email_is_blank():
    """A blank ``bot_user_email`` resolves to None — never provisions, never
    crashes — so the bridge stays safely inert."""
    plugin = BotMeinchatPlugin()
    plugin.initialize({"bot_user_email": ""})

    assert plugin._resolve_bot_user_id() is None


def test_initialize_merges_over_defaults():
    plugin = BotMeinchatPlugin()
    plugin.initialize({"bot_user_email": "designated@bot.local"})

    assert plugin._config["bot_user_email"] == "designated@bot.local"
    # Untouched keys keep their defaults.
    assert plugin._config["bot_nickname"] == "assistant"
    assert plugin._config["enabled"] is True
