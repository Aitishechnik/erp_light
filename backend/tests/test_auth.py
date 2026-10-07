"""Вход, роли и закрытость данных."""

from fastapi.testclient import TestClient

from app.services.auth import hash_password, verify_password


def test_login_returns_role(client: TestClient, login, logout) -> None:
    logout()
    assert client.get("/api/v1/auth/me").status_code == 401

    login("commercial")
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    body = me.json()
    assert body["login"] == "commercial"
    assert body["role"] == "commercial_director"
    assert body["role_title"] == "Коммерческий директор"


def test_wrong_password_is_rejected(client: TestClient, logout) -> None:
    logout()
    response = client.post("/api/v1/auth/login", json={"login": "sales", "password": "не тот"})
    assert response.status_code == 401


def test_data_requires_login(client: TestClient, logout) -> None:
    logout()
    for path in ("/api/v1/stock", "/api/v1/batches", "/api/v1/products", "/api/v1/sales-plans"):
        assert client.get(path).status_code == 401, path


def test_logout_closes_access(client: TestClient, logout) -> None:
    assert client.get("/api/v1/stock").status_code == 200
    logout()
    assert client.get("/api/v1/stock").status_code == 401


def test_sales_plans_are_closed_for_purchase_roles(client: TestClient, login) -> None:
    login("purchase")
    assert client.get("/api/v1/sales-plans").status_code == 403
    login("import")
    assert client.get("/api/v1/sales-plans").status_code == 403


def test_password_hash_roundtrip() -> None:
    stored = hash_password("секрет")
    assert "секрет" not in stored
    assert verify_password("секрет", stored)
    assert not verify_password("другой", stored)
    assert not verify_password("любой", "мусор")
