"""S70.2 — create `bot_meinchat_conversation_style`.

The portable, themeable bot-conversation style (one active at a time). Its
`tokens` JSON maps the fe-user `--vbwd-botchat-*` CSS vars to safe values
(whitelisted + sanitised in the service layer). bot_meinchat's first own
migration — anchored on the monolith root `vbwd_001` so it resolves standalone
(matches discount's first migration). Guarded + idempotent (monolith /
create_all dev DB / re-runs). Validated up → down → up.
"""
import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

# rev id ≤ 32 chars.
revision = "20260611_1100_bot_style"
down_revision = "vbwd_001"
branch_labels = None
depends_on = None

_TABLE = "bot_meinchat_conversation_style"


def _has_table(conn, table: str) -> bool:
    return sa.inspect(conn).has_table(table)


def upgrade() -> None:
    conn = op.get_bind()
    if _has_table(conn, _TABLE):
        return
    op.create_table(
        _TABLE,
        sa.Column("id", UUID(as_uuid=True), primary_key=True, nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("tokens", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.UniqueConstraint("name", name="uq_bot_meinchat_style_name"),
    )
    op.create_index(
        "ix_bot_meinchat_style_name", _TABLE, ["name"], unique=True
    )


def downgrade() -> None:
    conn = op.get_bind()
    if not _has_table(conn, _TABLE):
        return
    op.drop_index("ix_bot_meinchat_style_name", table_name=_TABLE)
    op.drop_table(_TABLE)
