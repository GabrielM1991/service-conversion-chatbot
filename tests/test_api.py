from fastapi.testclient import TestClient

from app.main import app


def test_webhook_acknowledges_valid_message_without_waiting_for_worker() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/webhooks/whatsapp",
            headers={"X-Tenant-ID": "ClinicaDental_01"},
            json={
                "message_id": "wamid-api-1",
                "from_phone": "+584121234567",
                "text": "Quiero una cita para limpieza dental",
            },
        )

        assert response.status_code == 202
        assert response.json() == {"status": "accepted", "message_id": "wamid-api-1"}


def test_health_reports_active_storage_adapter() -> None:
    with TestClient(app) as client:
        response = client.get("/health")

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "storage": "memory", "broker": "memory"}


def test_ready_succeeds_without_external_dependencies_in_memory_mode() -> None:
    with TestClient(app) as client:
        response = client.get("/ready")

        assert response.status_code == 200
        assert response.json() == {"status": "ready"}


def test_webhook_rejects_missing_tenant_header() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/webhooks/whatsapp",
            json={"message_id": "wamid-api-2", "from_phone": "+584121234567", "text": "Hola"},
        )

        assert response.status_code == 400


def test_webhook_does_not_cross_unknown_tenant_boundary() -> None:
    with TestClient(app) as client:
        response = client.post(
            "/webhooks/whatsapp",
            headers={"X-Tenant-ID": "tenant-inexistente"},
            json={"message_id": "wamid-api-3", "from_phone": "+584121234567", "text": "Hola"},
        )

        assert response.status_code == 404
