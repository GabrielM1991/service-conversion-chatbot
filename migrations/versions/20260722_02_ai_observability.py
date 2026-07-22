"""Add structured AI observability to outbound messages.

Revision ID: 20260722_02
Revises: 20260722_01
"""

from alembic import op
import sqlalchemy as sa

revision = "20260722_02"
down_revision = "20260722_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("messages", sa.Column("intent_confidence", sa.Float()))
    op.add_column("messages", sa.Column("requires_human", sa.Boolean()))
    op.add_column("messages", sa.Column("ai_source", sa.String(40)))
    op.add_column("messages", sa.Column("ai_model", sa.String(100)))
    op.add_column("messages", sa.Column("prompt_version", sa.String(80)))
    op.add_column("messages", sa.Column("input_tokens", sa.Integer()))
    op.add_column("messages", sa.Column("output_tokens", sa.Integer()))
    op.add_column("messages", sa.Column("ai_latency_ms", sa.Integer()))
    op.add_column("messages", sa.Column("fallback_used", sa.Boolean()))
    op.create_index(
        "ix_messages_tenant_ai_source_created",
        "messages",
        ["tenant_id", "ai_source", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_messages_tenant_ai_source_created", table_name="messages")
    for column in (
        "fallback_used",
        "ai_latency_ms",
        "output_tokens",
        "input_tokens",
        "prompt_version",
        "ai_model",
        "ai_source",
        "requires_human",
        "intent_confidence",
    ):
        op.drop_column("messages", column)
