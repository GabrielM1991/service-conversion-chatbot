"""Initial multi-tenant persistence with PostgreSQL RLS.

Revision ID: 20260722_01
Revises: None
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260722_01"
down_revision = None
branch_labels = None
depends_on = None

conversation_status = postgresql.ENUM(
    "OPEN", "QUALIFIED", "CLOSED", "OPTED_OUT", name="conversation_status", create_type=False
)
appointment_status = postgresql.ENUM(
    "PENDING", "CONFIRMED", "CANCELLED", name="appointment_status", create_type=False
)


def upgrade() -> None:
    conversation_status.create(op.get_bind(), checkfirst=True)
    appointment_status.create(op.get_bind(), checkfirst=True)

    op.create_table(
        "tenants",
        sa.Column("id", sa.String(80), primary_key=True),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("tone", sa.String(160), nullable=False),
        sa.Column("knowledge", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "services",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(80), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("name", sa.String(160), nullable=False),
        sa.Column("duration_minutes", sa.Integer(), nullable=False),
        sa.Column("price_minor", sa.Integer()),
        sa.Column("currency", sa.String(3), nullable=False, server_default="USD"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.CheckConstraint("duration_minutes > 0", name="ck_services_positive_duration"),
        sa.UniqueConstraint("tenant_id", "name", name="uq_services_tenant_name"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_services_tenant_id_id"),
    )
    op.create_index("ix_services_tenant_active", "services", ["tenant_id", "active"])
    op.create_table(
        "customers",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(80), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("phone", sa.String(32), nullable=False),
        sa.Column("name", sa.String(160)),
        sa.Column("opted_out_at", sa.DateTime(timezone=True)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("tenant_id", "phone", name="uq_customers_tenant_phone"),
        sa.UniqueConstraint("tenant_id", "id", name="uq_customers_tenant_id_id"),
    )
    op.create_index("ix_customers_tenant_created", "customers", ["tenant_id", "created_at"])
    op.create_table(
        "conversations",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(80), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", conversation_status, nullable=False),
        sa.Column("qualification", postgresql.JSONB(), nullable=False, server_default="{}"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["tenant_id", "customer_id"], ["customers.tenant_id", "customers.id"],
            ondelete="CASCADE", name="fk_conversations_tenant_customer",
        ),
        sa.UniqueConstraint("tenant_id", "id", name="uq_conversations_tenant_id_id"),
    )
    op.create_index("ix_conversations_tenant_status", "conversations", ["tenant_id", "status"])
    op.create_table(
        "messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(80), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("conversation_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("provider_message_id", sa.String(190), nullable=False),
        sa.Column("direction", sa.String(8), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("intent", sa.String(80)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["tenant_id", "conversation_id"], ["conversations.tenant_id", "conversations.id"],
            ondelete="CASCADE", name="fk_messages_tenant_conversation",
        ),
        sa.CheckConstraint("direction IN ('inbound', 'outbound')", name="ck_messages_direction"),
        sa.UniqueConstraint("tenant_id", "provider_message_id", name="uq_messages_provider_id"),
    )
    op.create_index(
        "ix_messages_conversation_created", "messages", ["tenant_id", "conversation_id", "created_at"]
    )
    op.create_table(
        "appointments",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("tenant_id", sa.String(80), sa.ForeignKey("tenants.id", ondelete="CASCADE"), nullable=False),
        sa.Column("customer_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("service_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("starts_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ends_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", appointment_status, nullable=False),
        sa.Column("external_calendar_id", sa.String(190)),
        sa.Column("payment_reference", sa.String(190)),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("ends_at > starts_at", name="ck_appointments_valid_range"),
        sa.ForeignKeyConstraint(
            ["tenant_id", "customer_id"], ["customers.tenant_id", "customers.id"],
            name="fk_appointments_tenant_customer",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "service_id"], ["services.tenant_id", "services.id"],
            name="fk_appointments_tenant_service",
        ),
    )
    op.create_index("ix_appointments_tenant_starts", "appointments", ["tenant_id", "starts_at"])

    for table in ("services", "customers", "conversations", "messages", "appointments"):
        op.execute(f'ALTER TABLE "{table}" ENABLE ROW LEVEL SECURITY')
        op.execute(f'ALTER TABLE "{table}" FORCE ROW LEVEL SECURITY')
        op.execute(
            f'''CREATE POLICY {table}_tenant_isolation ON "{table}"
                USING (tenant_id = current_setting('app.tenant_id', true))
                WITH CHECK (tenant_id = current_setting('app.tenant_id', true))'''
        )


def downgrade() -> None:
    for table in ("appointments", "messages", "conversations", "customers", "services"):
        op.drop_table(table)
    op.drop_table("tenants")
    appointment_status.drop(op.get_bind(), checkfirst=True)
    conversation_status.drop(op.get_bind(), checkfirst=True)
