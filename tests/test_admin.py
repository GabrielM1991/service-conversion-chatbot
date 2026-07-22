from __future__ import annotations

import io

from cryptography.fernet import Fernet
from fastapi.testclient import TestClient
from PIL import Image

from app.infrastructure.secrets import SecretCipher
from app.main import app


def test_admin_panel_and_tenant_settings_are_available_in_development() -> None:
    with TestClient(app) as client:
        page = client.get("/admin")
        settings = client.get("/admin/api/tenants/ClinicaDental_01/settings")

    assert page.status_code == 200
    assert "Entrena y personaliza" in page.text
    assert settings.status_code == 200
    assert settings.json()["bot_name"] == "Asistente"
    assert settings.json()["encryption_available"] is False


def test_text_knowledge_is_isolated_by_tenant_and_can_be_deleted() -> None:
    with TestClient(app) as client:
        created = client.post(
            "/admin/api/tenants/ClinicaDental_01/knowledge/text",
            json={"title": "Garantía", "text": "La garantía del servicio dura 30 días."},
        )
        source_id = created.json()["id"]
        clinic = client.get("/admin/api/tenants/ClinicaDental_01/knowledge")
        reforms = client.get("/admin/api/tenants/Reformas_01/knowledge")
        cross_tenant = client.delete(
            f"/admin/api/tenants/Reformas_01/knowledge/{source_id}"
        )
        deleted = client.delete(
            f"/admin/api/tenants/ClinicaDental_01/knowledge/{source_id}"
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
        response = client.post(
            "/admin/api/tenants/ClinicaDental_01/knowledge/file",
            data={"title": "Recepción", "description": "La recepción tiene una puerta verde."},
            files={"file": ("recepcion.png", image_bytes.getvalue(), "image/png")},
        )
        source_id = response.json()["id"]
        deleted = client.delete(
            f"/admin/api/tenants/ClinicaDental_01/knowledge/{source_id}"
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
