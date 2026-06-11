"""Whitelist + sanitise the bot-conversation style ``tokens`` (S70.2 §Security).

The ``tokens`` map themes the fe-user ``--vbwd-botchat-*`` CSS custom
properties (S70.1). Only the known keys are accepted, and each value must match
a narrow safe pattern (a hex/rgb color, a length/radius token, or a small
keyword) — NO arbitrary CSS, so nothing like ``;``, ``{}``, ``url(...)`` or
``expression(...)`` can ride into the custom properties the fe applies.
Unknown keys or unsafe values raise :class:`StyleTokenError` (the route maps
that to a 400).
"""
import re
from typing import Any, Dict

# The whitelisted `--vbwd-botchat-*` vars (S70.1). Keys are the var suffixes.
ALLOWED_TOKEN_KEYS = frozenset(
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

# A token value is at most this many characters (a CSS color/length is short).
MAX_TOKEN_VALUE_LENGTH = 64

# A safe value is exactly one of:
#   * a hex color (#rgb / #rrggbb / #rrggbbaa),
#   * an rgb()/rgba() color with numeric/percent/space/comma/dot args only,
#   * a numeric length/radius (digits, optional decimal, optional unit),
#   * a short bare keyword (transparent, inherit, currentColor, …).
# Crucially it forbids `;`, `{`, `}`, `url(`, `expression(`, comments, and any
# parenthesis that is not a well-formed rgb()/rgba() call.
_HEX_COLOR = re.compile(r"^#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_RGB_COLOR = re.compile(r"^rgba?\(\s*[0-9.,%\s]+\)$")
_LENGTH = re.compile(r"^-?\d+(?:\.\d+)?(?:px|rem|em|%|vh|vw)?$")
_KEYWORD = re.compile(r"^[a-zA-Z][a-zA-Z-]{0,31}$")


class StyleTokenError(ValueError):
    """Raised when style tokens contain an unknown key or unsafe value."""


def _value_is_safe(value: str) -> bool:
    return bool(
        _HEX_COLOR.match(value)
        or _RGB_COLOR.match(value)
        or _LENGTH.match(value)
        or _KEYWORD.match(value)
    )


def sanitise_style_tokens(tokens: Any) -> Dict[str, str]:
    """Return ``tokens`` unchanged if every key is whitelisted and every value
    is safe; otherwise raise :class:`StyleTokenError`.

    Accepts an empty map. The returned map is a plain ``dict[str, str]`` copy.
    """
    if not isinstance(tokens, dict):
        raise StyleTokenError("tokens must be an object")

    sanitised: Dict[str, str] = {}
    for key, value in tokens.items():
        if key not in ALLOWED_TOKEN_KEYS:
            raise StyleTokenError(f"unknown style token '{key}'")
        if not isinstance(value, str):
            raise StyleTokenError(f"token '{key}' must be a string")
        if not value or len(value) > MAX_TOKEN_VALUE_LENGTH:
            raise StyleTokenError(f"token '{key}' has an invalid length")
        if not _value_is_safe(value):
            raise StyleTokenError(f"token '{key}' has an unsafe value")
        sanitised[key] = value
    return sanitised
