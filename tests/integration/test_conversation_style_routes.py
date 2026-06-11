"""Integration: bot-conversation style routes — admin CRUD, activate, public read.

Boots the full app (bot-meinchat enabled via plugins.json) so the blueprint is
mounted. Admin auth uses core's auth service to register + promote a user (an
ADMIN with no RBAC access levels gets all permissions, so it carries
``bot_meinchat.manage``); a regular user is rejected. The public active-style
read needs no auth. Test data is created only through the admin route / core
auth service / seed service (never raw SQL).
"""
import uuid

import pytest

from vbwd.models.enums import UserRole

_TOKENS = {"accent": "#3182ce", "card_bg": "#ffffff", "card_radius": "12px"}


def _register_user(app, email: str):
    from vbwd.extensions import db
    from vbwd.repositories.user_repository import UserRepository

    auth_service = app.container.auth_service()
    unique_email = email.replace("@", f"+{uuid.uuid4().hex[:8]}@")
    result = auth_service.register(email=unique_email, password="BotStyle123@")
    db.session.commit()
    user = UserRepository(db.session).find_by_id(result.user_id)
    return str(user.id), result.token


def _promote_to_admin(app, user_id: str) -> None:
    from vbwd.extensions import db
    from vbwd.repositories.user_repository import UserRepository

    repository = UserRepository(db.session)
    user = repository.find_by_id(user_id)
    user.role = UserRole.ADMIN
    db.session.commit()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _admin_headers(app):
    with app.app_context():
        user_id, token = _register_user(app, "styleadmin@example.com")
        _promote_to_admin(app, user_id)
    return _auth(token)


@pytest.fixture(autouse=True)
def _clean_styles(app):
    """Each route test starts from an empty style table (no raw SQL)."""
    from vbwd.extensions import db
    from plugins.bot_meinchat.bot_meinchat.models.conversation_style import (
        BotConversationStyle,
    )

    with app.app_context():
        db.session.query(BotConversationStyle).delete()
        db.session.commit()
    yield
    with app.app_context():
        db.session.query(BotConversationStyle).delete()
        db.session.commit()


def _create_style(client, headers, **overrides):
    body = {
        "name": overrides.get("name", f"style-{uuid.uuid4().hex[:6]}"),
        "tokens": overrides.get("tokens", dict(_TOKENS)),
        "is_active": overrides.get("is_active", False),
    }
    return client.post("/api/v1/admin/bot-styles", json=body, headers=headers)


# ── permission enforcement ───────────────────────────────────────────────────
@pytest.mark.integration
def test_list_requires_authentication(client):
    response = client.get("/api/v1/admin/bot-styles")
    assert response.status_code == 401


@pytest.mark.integration
def test_list_forbidden_for_regular_user(app, client):
    with app.app_context():
        _user_id, token = _register_user(app, "plainstyle@example.com")
    response = client.get("/api/v1/admin/bot-styles", headers=_auth(token))
    assert response.status_code == 403


# ── admin CRUD ───────────────────────────────────────────────────────────────
@pytest.mark.integration
def test_create_then_get_style(app, client):
    headers = _admin_headers(app)
    create = _create_style(client, headers, name="Branded")
    assert create.status_code == 201
    created = create.get_json()
    assert created["name"] == "Branded"
    assert created["tokens"] == _TOKENS

    fetched = client.get(
        f"/api/v1/admin/bot-styles/{created['id']}", headers=headers
    )
    assert fetched.status_code == 200
    assert fetched.get_json()["name"] == "Branded"


@pytest.mark.integration
def test_create_rejects_unsafe_token_value(app, client):
    headers = _admin_headers(app)
    response = _create_style(
        client, headers, tokens={"accent": "red; background: url(http://evil)"}
    )
    assert response.status_code == 400


@pytest.mark.integration
def test_create_rejects_unknown_token_key(app, client):
    headers = _admin_headers(app)
    response = _create_style(client, headers, tokens={"evil": "#000000"})
    assert response.status_code == 400


@pytest.mark.integration
def test_update_and_delete_style(app, client):
    headers = _admin_headers(app)
    created = _create_style(client, headers).get_json()

    update = client.put(
        f"/api/v1/admin/bot-styles/{created['id']}",
        json={"name": "Renamed", "tokens": {"accent": "#222222"}},
        headers=headers,
    )
    assert update.status_code == 200
    assert update.get_json()["name"] == "Renamed"
    assert update.get_json()["tokens"] == {"accent": "#222222"}

    deleted = client.delete(
        f"/api/v1/admin/bot-styles/{created['id']}", headers=headers
    )
    assert deleted.status_code == 200
    assert deleted.get_json()["deleted"] is True


# ── activate + public read ───────────────────────────────────────────────────
@pytest.mark.integration
def test_activate_sets_single_active_and_public_read_returns_it(app, client):
    headers = _admin_headers(app)
    first = _create_style(client, headers, name="First").get_json()
    second = _create_style(client, headers, name="Second").get_json()

    activate = client.post(
        f"/api/v1/admin/bot-styles/{second['id']}/activate", headers=headers
    )
    assert activate.status_code == 200
    assert activate.get_json()["is_active"] is True

    # Public read (no auth) returns the active style as {name, tokens}.
    public = client.get("/api/v1/bot-conversation-style/active")
    assert public.status_code == 200
    body = public.get_json()
    assert body["name"] == "Second"
    assert body["tokens"] == _TOKENS

    # The first style is no longer active (exactly-one-active).
    first_row = client.get(
        f"/api/v1/admin/bot-styles/{first['id']}", headers=headers
    ).get_json()
    assert first_row["is_active"] is False


@pytest.mark.integration
def test_public_active_read_needs_no_auth_and_handles_empty(client):
    response = client.get("/api/v1/bot-conversation-style/active")
    assert response.status_code == 200
    body = response.get_json()
    assert body == {"name": None, "tokens": {}}
