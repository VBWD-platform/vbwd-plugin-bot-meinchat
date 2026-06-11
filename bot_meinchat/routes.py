"""Flask Blueprint for the bot-conversation style (S70.2).

Admin CRUD + set-active (gated by ``bot_meinchat.manage``) plus a single public
read the fe-user calls to theme the bot chat. Multiple prefixes (public +
admin) → ``get_url_prefix()`` returns ``""`` and routes use absolute paths.

The style ``tokens`` are whitelisted + sanitised on every write
(``style_token_validation``) — unknown keys / unsafe values return 400.
"""
from flask import Blueprint, jsonify, request

from vbwd.extensions import db
from vbwd.middleware.auth import require_admin, require_auth, require_permission
from plugins.bot_meinchat.bot_meinchat.models.conversation_style import (
    BotConversationStyle,
)
from plugins.bot_meinchat.bot_meinchat.repositories.conversation_style_repository import (  # noqa: E501
    BotConversationStyleRepository,
)
from plugins.bot_meinchat.bot_meinchat.services.style_token_validation import (
    StyleTokenError,
    sanitise_style_tokens,
)

MANAGE_PERMISSION = "bot_meinchat.manage"

bot_meinchat_bp = Blueprint("bot_meinchat", __name__)


def _repository() -> BotConversationStyleRepository:
    return BotConversationStyleRepository(db.session)


# ── public ────────────────────────────────────────────────────────────────


@bot_meinchat_bp.route("/api/v1/bot-conversation-style/active", methods=["GET"])
def get_active_style():
    """The active bot-conversation style the fe-user applies as CSS vars.

    No auth — the look is public (it themes a public chat surface). Returns
    ``{name, tokens}``; ``null`` for both when no style is active yet.
    """
    active = _repository().find_active()
    if active is None:
        return jsonify({"name": None, "tokens": {}}), 200
    return jsonify({"name": active.name, "tokens": dict(active.tokens or {})}), 200


# ── admin ─────────────────────────────────────────────────────────────────


@bot_meinchat_bp.route("/api/v1/admin/bot-styles", methods=["GET"])
@require_auth
@require_admin
@require_permission(MANAGE_PERMISSION)
def admin_list_styles():
    rows = _repository().find_all()
    return jsonify({"items": [row.to_dict() for row in rows]}), 200


@bot_meinchat_bp.route("/api/v1/admin/bot-styles", methods=["POST"])
@require_auth
@require_admin
@require_permission(MANAGE_PERMISSION)
def admin_create_style():
    payload = request.get_json(silent=True) or {}
    name = (payload.get("name") or "").strip()
    if not name:
        return jsonify({"error": "name is required"}), 400
    repository = _repository()
    if repository.find_by_name(name) is not None:
        return jsonify({"error": "a style with that name already exists"}), 409
    try:
        tokens = sanitise_style_tokens(payload.get("tokens") or {})
    except StyleTokenError as error:
        return jsonify({"error": str(error)}), 400

    style = BotConversationStyle(
        name=name, is_active=bool(payload.get("is_active")), tokens=tokens
    )
    repository.add(style)
    if style.is_active:
        db.session.flush()
        repository.set_active(style.id)
    db.session.commit()
    return jsonify(style.to_dict()), 201


@bot_meinchat_bp.route("/api/v1/admin/bot-styles/<style_id>", methods=["GET"])
@require_auth
@require_admin
@require_permission(MANAGE_PERMISSION)
def admin_get_style(style_id: str):
    style = _repository().find_by_id(style_id)
    if style is None:
        return jsonify({"error": "style not found"}), 404
    return jsonify(style.to_dict()), 200


@bot_meinchat_bp.route("/api/v1/admin/bot-styles/<style_id>", methods=["PUT"])
@require_auth
@require_admin
@require_permission(MANAGE_PERMISSION)
def admin_update_style(style_id: str):
    repository = _repository()
    style = repository.find_by_id(style_id)
    if style is None:
        return jsonify({"error": "style not found"}), 404
    payload = request.get_json(silent=True) or {}

    if "name" in payload:
        name = (payload.get("name") or "").strip()
        if not name:
            return jsonify({"error": "name cannot be empty"}), 400
        clashing = repository.find_by_name(name)
        if clashing is not None and str(clashing.id) != str(style.id):
            return jsonify({"error": "a style with that name already exists"}), 409
        style.name = name
    if "tokens" in payload:
        try:
            style.tokens = sanitise_style_tokens(payload.get("tokens") or {})
        except StyleTokenError as error:
            return jsonify({"error": str(error)}), 400

    db.session.commit()
    return jsonify(style.to_dict()), 200


@bot_meinchat_bp.route("/api/v1/admin/bot-styles/<style_id>", methods=["DELETE"])
@require_auth
@require_admin
@require_permission(MANAGE_PERMISSION)
def admin_delete_style(style_id: str):
    repository = _repository()
    style = repository.find_by_id(style_id)
    if style is None:
        return jsonify({"error": "style not found"}), 404
    repository.delete(style)
    db.session.commit()
    return jsonify({"deleted": True}), 200


@bot_meinchat_bp.route("/api/v1/admin/bot-styles/<style_id>/activate", methods=["POST"])
@require_auth
@require_admin
@require_permission(MANAGE_PERMISSION)
def admin_activate_style(style_id: str):
    repository = _repository()
    activated = repository.set_active(style_id)
    if activated is None:
        return jsonify({"error": "style not found"}), 404
    db.session.commit()
    return jsonify(activated.to_dict()), 200
