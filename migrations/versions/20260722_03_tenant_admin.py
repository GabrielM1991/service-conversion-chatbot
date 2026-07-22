"""Add tenant bot settings, encrypted AI configuration and knowledge sources.

Revision ID: 20260722_03
Revises: 20260722_02
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260722_03"
down_revision = "20260722_02"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("tenants", sa.Column("bot_name", sa.String(120), nullable=False, server_default="Asistente"))
    op.add_column("tenants", sa.Column("welcome_message", sa.Text(), nullable=False, server_default="Hola, ¿cómo puedo ayudarte?"))
    op.add_column("tenants", sa.Column("system_instructions", sa.Text(), nullable=False, server_default=""))
    op.create_table(
        "tenant_ai_configurations",
        sa.Column("tenant_id", sa.String(80), sa.ForeignKey("tenants.id", ondelete="CASCADE"), primary_key=True),
        sa.Column("provider", sa.String(40), nullable=False, server_default="openai"),
        sa.Column("model", sa.String(100), nullable=False, server_default="gpt-5.6-sol"),
        sa.Column("encrypted_api_key", sa.Text()),
        sa.Column("key_last_four", sa.String(4)),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "knowledge_sources",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(80), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("title", sa.String(180), nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("filename", sa.String(255)),
        sa.Column("content_type", sa.String(120)),
        sa.Column("size_bytes", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("storage_key", sa.String(255)),
        sa.Column("extracted_text", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("kind IN ('text', 'pdf', 'image')", name="ck_knowledge_kind"),
        sa.CheckConstraint("status IN ('ready', 'stored', 'failed')", name="ck_knowledge_status"),
    )
    op.create_index("ix_knowledge_tenant_created", "knowledge_sources", ["tenant_id", "created_at"])
    for table in ("tenant_ai_configurations", "knowledge_sources"):
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'''CREATE POLICY {table}_tenant_isolation ON "{table}"
                USING (tenant_id = current_setting('app.tenant_id', true))
                WITH CHECK (tenant_id = current_setting('app.tenant_id', true))'''
        )


def downgrade() -> None:
    op.drop_table("knowledge_sources")
    op.drop_table("tenant_ai_configurations")
    op.drop_column("tenants", "system_instructions")
    op.drop_column("tenants", "welcome_message")
    op.drop_column("tenants", "bot_name")
