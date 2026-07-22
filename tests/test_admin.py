from __future__ import annotations

import io

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from PIL import Image

from app.infrastructure.secrets import SecretCipher
from app.main import app


def authenticate(client: TestClient) -> dict[str, str]:
    response = client.post(
        "/auth/login",
        json={
            "email": "admin@serviceflow.local",
            "password": "ServiceFlow-local-2026!",
        },
    )
    assert response.status_code == 200
    return {"X-CSRF-Token": client.cookies["serviceflow_csrf"]}


def test_admin_panel_and_tenant_settings_are_available_in_development() -> None:
    with TestClient(app) as client:
        redirect = client.get("/admin", follow_redirects=False)
        unauthorized = client.get("/admin/api/tenants")
        authenticate(client)
        page = client.get("/admin")
        settings = client.get("/admin/api/tenants/ClinicaDental_01/settings")

    assert redirect.status_code == 303
    assert redirect.headers["location"] == "/login"
    assert unauthorized.status_code == 401
    assert page.status_code == 200
    assert "Entrena y personaliza" in page.text
    assert settings.status_code == 200
    assert settings.json()["bot_name"] == "Asistente"
    assert settings.json()["encryption_available"] is False


def test_text_knowledge_is_isolated_by_tenant_and_can_be_deleted() -> None:
    with TestClient(app) as client:
        csrf = authenticate(client)
        created = client.post(
            "/admin/api/tenants/ClinicaDental_01/knowledge/text",
            json={"title": "Garantía", "text": "La garantía del servicio dura 30 días."},
            headers=csrf,
        )
        source_id = created.json()["id"]
        clinic = client.get("/admin/api/tenants/ClinicaDental_01/knowledge")
        reforms = client.get("/admin/api/tenants/Reformas_01/knowledge")
        cross_tenant = client.delete(
            f"/admin/api/tenants/Reformas_01/knowledge/{source_id}", headers=csrf
        )
        deleted = client.delete(
            f"/admin/api/tenants/ClinicaDental_01/knowledge/{source_id}", headers=csrf
        )

    assert created.status_code == 200
    assert any(item["id"] == source_id for item in clinic.json())
    assert all(item["id"] != source_id for item in reforms.json())
    assert cross_tenant.status_code == 404
    assert deleted.status_code == 200


def test_image_upload_uses_description_as_searchable_knowledge() -> None:
    image_bytes = io.BytesIO()
    Image.new("RGB", (4, 4), color=(20, 100, 70)).save(image_bytes, format="PNG")

    with TestClient(app) as client:
        csrf = authenticate(client)
        response = client.post(
            "/admin/api/tenants/ClinicaDental_01/knowledge/file",
            data={"title": "Recepción", "description": "La recepción tiene una puerta verde."},
            files={"file": ("recepcion.png", image_bytes.getvalue(), "image/png")},
            headers=csrf,
        )
        source_id = response.json()["id"]
        deleted = client.delete(
            f"/admin/api/tenants/ClinicaDental_01/knowledge/{source_id}", headers=csrf
        )

    assert response.status_code == 200
    assert response.json()["kind"] == "image"
    assert response.json()["status"] == "ready"
    assert deleted.status_code == 200


def test_tenant_api_keys_are_encrypted_and_never_stored_as_plaintext() -> None:
    cipher = SecretCipher(Fernet.generate_key().decode("ascii"))
    secret = "sk-example-private-key"

    encrypted = cipher.encrypt(secret)

    assert secret not in encrypted
    assert cipher.decrypt(encrypted) == secret


def test_login_is_generic_and_mutations_require_csrf() -> None:
    with TestClient(app) as client:
        invalid = client.post(
            "/auth/login",
            json={"email": "nobody@example.com", "password": "incorrect-password"},
        )
        authenticate(client)
        without_csrf = client.post(
            "/admin/api/tenants/ClinicaDental_01/knowledge/text",
            json={"title": "Bloqueado", "text": "Este texto no debe guardarse."},
        )

    assert invalid.status_code == 401
    assert invalid.json()["detail"] == "Correo o contraseña incorrectos"
    assert without_csrf.status_code == 403


def test_logout_invalidates_the_server_side_session() -> None:
    with TestClient(app) as client:
        csrf = authenticate(client)
        before = client.get("/auth/me")
        logout = client.post("/auth/logout", headers=csrf)
        after = client.get("/auth/me")

    assert before.status_code == 200
    assert before.json()["memberships"][0]["role"] == "owner"
    assert logout.status_code == 200
    assert after.status_code == 401
