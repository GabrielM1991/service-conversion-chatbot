from __future__ import annotations

import asyncio
import os
import uuid

from sqlalchemy import select, text

from app.infrastructure.database import create_database_engine, create_session_factory
from app.infrastructure.orm import ServiceRow, TenantRow

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

