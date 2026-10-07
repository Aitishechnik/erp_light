"""Справочники: клиенты и номенклатура — заведение, правка, права."""

from fastapi.testclient import TestClient


def test_client_can_be_created_and_listed(client: TestClient, login) -> None:
    login("sales")
    created = client.post("/api/v1/clients", json={"name": "ООО Ромашка", "inn": "7701234567"})
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == "ООО Ромашка"
    assert body["is_active"] is True

    listed = client.get("/api/v1/clients").json()
    assert [row["name"] for row in listed] == ["ООО Ромашка"]


def test_duplicate_client_name_is_rejected(client: TestClient, login) -> None:
    login("sales")
    client.post("/api/v1/clients", json={"name": "ООО Ромашка"})
    again = client.post("/api/v1/clients", json={"name": "ООО Ромашка"})
    assert again.status_code == 409
    assert "уже есть" in again.json()["detail"]


def test_client_can_be_deactivated(client: TestClient, login) -> None:
    login("sales")
    created = client.post("/api/v1/clients", json={"name": "ООО Вектор"}).json()
    updated = client.patch(f"/api/v1/clients/{created['id']}", json={"is_active": False})
    assert updated.status_code == 200, updated.text
    assert updated.json()["is_active"] is False

    assert client.get("/api/v1/clients").json() == []
    assert len(client.get("/api/v1/clients", params={"include_inactive": True}).json()) == 1


def test_product_can_be_created_and_edited(client: TestClient, login) -> None:
    login("sales")
    created = client.post(
        "/api/v1/products",
        json={"code": "SKU-900", "name": "Краска белая", "kind": "goods", "unit": "шт"},
    )
    assert created.status_code == 201, created.text
    product_id = created.json()["id"]

    duplicate = client.post(
        "/api/v1/products", json={"code": "SKU-900", "name": "Дубль", "unit": "шт"}
    )
    assert duplicate.status_code == 409

    updated = client.patch(
        f"/api/v1/products/{product_id}", json={"name": "Краска белая 20 кг", "unit": "кг"}
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Краска белая 20 кг"
    assert updated.json()["unit"] == "кг"


def test_unknown_product_kind_is_rejected(client: TestClient, login) -> None:
    login("sales")
    response = client.post(
        "/api/v1/products", json={"code": "SKU-901", "name": "Мусор", "kind": "unknown"}
    )
    assert response.status_code == 400
    assert "Вид номенклатуры" in response.json()["detail"]


def test_import_manager_cannot_edit_directories(client: TestClient, login) -> None:
    login("import")
    assert client.post("/api/v1/clients", json={"name": "ООО Поздний"}).status_code == 403
    assert (
        client.post("/api/v1/products", json={"code": "SKU-902", "name": "Поздний"}).status_code
        == 403
    )
    # Читать справочники можно всем, кто вошёл.
    assert client.get("/api/v1/clients").status_code == 200
    assert client.get("/api/v1/products").status_code == 200


def test_purchase_director_can_edit_directories(client: TestClient, login) -> None:
    login("purchase")
    assert client.post("/api/v1/clients", json={"name": "ООО Закупки"}).status_code == 201
