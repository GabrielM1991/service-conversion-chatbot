from __future__ import annotations

import asyncio
import os
import uuid

from sqlalchemy import select, text

from app.infrastructure.database import create_database_engine, create_session_factory
from app.infrastructure.auth import PasswordService
from app.infrastructure.orm import ServiceRow, TenantMembershipRow, TenantRow, UserRow

TENANTS = (
    {
        "id": "ClinicaDental_01",
        "name": "Clínica Dental Sonrisa",
        "tone": "cercano y profesional",
        "knowledge": {"precio": "La limpieza dental cuesta desde 50 USD."},
        "services": (("limpieza dental", 45, 5000), ("ortodoncia", 60, None)),
    },
    {
        "id": "Reformas_01",
        "name": "Reformas Horizonte",
        "tone": "directo y resolutivo",
        "knowledge": {"zona": "Trabajamos en toda el área metropolitana."},
        "services": (("visita técnica", 60, 2500),),
    },
)


async def seed() -> None:
    database_url = os.environ["DATABASE_URL"]
    engine = create_database_engine(database_url)
    sessions = create_session_factory(engine)
    try:
        async with sessions() as session, session.begin():
            for data in TENANTS:
                existing = await session.get(TenantRow, data["id"])
                if existing is None:
                    session.add(
                        TenantRow(
                            id=data["id"],
                            name=data["name"],
                            tone=data["tone"],
                            knowledge=data["knowledge"],
                        )
                    )
            await session.flush()

            production = os.getenv("APP_ENV", "development") != "development"
            admin_email = os.getenv("BOOTSTRAP_ADMIN_EMAIL")
            admin_password = os.getenv("BOOTSTRAP_ADMIN_PASSWORD")
            if production and (not admin_email or not admin_password):
                raise RuntimeError(
                    "BOOTSTRAP_ADMIN_EMAIL y BOOTSTRAP_ADMIN_PASSWORD son obligatorios"
                )
            admin_email = (admin_email or "admin@serviceflow.local").casefold()
            admin_password = admin_password or "ServiceFlow-local-2026!"
            admin = await session.scalar(select(UserRow).where(UserRow.email == admin_email))
            if admin is None:
                admin = UserRow(
                    id=uuid.UUID("00000000-0000-0000-0000-000000000001"),
                    email=admin_email,
                    password_hash=PasswordService().hash(admin_password),
                )
                session.add(admin)
                await session.flush()
            for data in TENANTS:
                membership = await session.get(
                    TenantMembershipRow, (data["id"], admin.id)
                )
                if membership is None:
                    session.add(
                        TenantMembershipRow(
                            tenant_id=data["id"], user_id=admin.id, role="owner"
                        )
                    )

        for data in TENANTS:
            async with sessions() as session, session.begin():
                await session.execute(
                    text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
                    {"tenant_id": data["id"]},
                )
                existing_names = set(
                    await session.scalars(
                        select(ServiceRow.name).where(ServiceRow.tenant_id == data["id"])
                    )
                )
                for name, duration, price in data["services"]:
                    if name not in existing_names:
                        session.add(
                            ServiceRow(
                                id=uuid.uuid4(),
                                tenant_id=data["id"],
                                name=name,
                                duration_minutes=duration,
                                price_minor=price,
                            )
                        )
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(seed())
