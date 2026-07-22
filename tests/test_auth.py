from __future__ import annotations

from datetime import timedelta
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from app.domain.models import TenantMembership, UserAccount
from app.infrastructure.auth import (
    SESSION_COOKIE,
    InMemoryAuthRepository,
    PasswordService,
    hash_session_token,
    new_session_token,
    session_expiration,
)
from app.main import require_tenant_access


def test_passwords_use_argon2_and_reject_an_incorrect_value() -> None:
    passwords = PasswordService()
    encoded = passwords.hash("a-strong-password")

    assert encoded.startswith("$argon2")
    assert passwords.verify(encoded, "a-strong-password") is True
    assert passwords.verify(encoded, "wrong-password") is False


@pytest.mark.asyncio
async def test_sessions_store_a_hash_and_expire_server_side() -> None:
    passwords = PasswordService()
    user = UserAccount(
        "00000000-0000-0000-0000-000000000099",
        "viewer@example.com",
        passwords.hash("viewer-password"),
        (TenantMembership("ClinicaDental_01", "viewer"),),
    )
    repository = InMemoryAuthRepository([user])
    token = new_session_token()
    await repository.create_session(
        user.id, hash_session_token(token), session_expiration(1)
    )

    active = await repository.get_session(
        hash_session_token(token), session_expiration(1) - timedelta(minutes=59)
    )
    expired = await repository.get_session(
        hash_session_token(token), session_expiration(2)
    )

    assert active is not None
    assert expired is None
    assert token not in repository._sessions


@pytest.mark.asyncio
async def test_viewer_can_read_only_its_assigned_tenant() -> None:
    passwords = PasswordService()
    user = UserAccount(
        "00000000-0000-0000-0000-000000000098",
        "readonly@example.com",
        passwords.hash("viewer-password"),
        (TenantMembership("ClinicaDental_01", "viewer"),),
    )
    repository = InMemoryAuthRepository([user])
    token = new_session_token()
    await repository.create_session(
        user.id, hash_session_token(token), session_expiration(1)
    )
    request = SimpleNamespace(
        cookies={SESSION_COOKIE: token},
        state=SimpleNamespace(),
        app=SimpleNamespace(state=SimpleNamespace(container=SimpleNamespace(auth=repository))),
    )

    _, role = await require_tenant_access(request, "ClinicaDental_01")
    with pytest.raises(HTTPException) as write_error:
        await require_tenant_access(request, "ClinicaDental_01", write=True)
    with pytest.raises(HTTPException) as tenant_error:
        await require_tenant_access(request, "Reformas_01")

    assert role == "viewer"
    assert write_error.value.status_code == 403
    assert tenant_error.value.status_code == 404
