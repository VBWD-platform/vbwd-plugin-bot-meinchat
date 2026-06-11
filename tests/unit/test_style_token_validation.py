"""Unit: bot-conversation style token whitelist + sanitisation (S70.2 §Security).

The ``tokens`` map is a *whitelisted* set of ``--vbwd-botchat-*`` CSS-var
values. Only the known keys are accepted; values are checked against a safe
pattern (color / length / radius token) so no arbitrary CSS — no ``;{}()``,
no ``url(`` injection — can ride into the fe-user's custom properties.
"""
import pytest

from plugins.bot_meinchat.bot_meinchat.services.style_token_validation import (
    ALLOWED_TOKEN_KEYS,
    StyleTokenError,
    sanitise_style_tokens,
)


class TestWhitelistKeys:
    def test_known_keys_accepted(self):
        tokens = {
            "card_bg": "#ffffff",
            "card_border": "#e2e8f0",
            "card_radius": "12px",
            "card_fg": "#1a202c",
            "accent": "#3182ce",
            "badge_bg": "#3182ce",
            "badge_fg": "#ffffff",
            "hint": "#718096",
            "gap": "8px",
        }
        assert sanitise_style_tokens(tokens) == tokens

    def test_all_documented_keys_are_whitelisted(self):
        assert ALLOWED_TOKEN_KEYS == frozenset(
            {
                "card_bg",
                "card_border",
                "card_radius",
                "card_fg",
                "accent",
                "badge_bg",
                "badge_fg",
                "hint",
                "gap",
            }
        )

    def test_unknown_key_rejected(self):
        with pytest.raises(StyleTokenError):
            sanitise_style_tokens({"card_bg": "#fff", "evil": "#000"})

    def test_empty_map_is_valid(self):
        assert sanitise_style_tokens({}) == {}

    def test_non_mapping_rejected(self):
        with pytest.raises(StyleTokenError):
            sanitise_style_tokens(["#fff"])


class TestValueSanitisation:
    @pytest.mark.parametrize(
        "value",
        [
            "#fff",
            "#ffffff",
            "rgb(10, 20, 30)",
            "rgba(10, 20, 30, 0.5)",
            "12px",
            "0.5rem",
            "8",
            "transparent",
        ],
    )
    def test_safe_values_accepted(self, value):
        assert sanitise_style_tokens({"accent": value}) == {"accent": value}

    @pytest.mark.parametrize(
        "value",
        [
            "red; background: url(http://evil)",
            "url(http://evil)",
            "}body{display:none",
            "expression(alert(1))",
            "#fff /* comment */",
            "<script>",
            "calc(100% - 10px)",  # parens not allowed except rgb/rgba
            "",
            "x" * 65,  # over length cap
        ],
    )
    def test_unsafe_values_rejected(self, value):
        with pytest.raises(StyleTokenError):
            sanitise_style_tokens({"accent": value})

    def test_non_string_value_rejected(self):
        with pytest.raises(StyleTokenError):
            sanitise_style_tokens({"accent": 123})
