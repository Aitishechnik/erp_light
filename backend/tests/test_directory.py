"""Справочники: контрагенты и номенклатура — заведение, правка, права."""

from fastapi.testclient import TestClient


def test_counterparty_can_be_created_and_listed(client: TestClient, login) -> None:
    login("sales")
    created = client.post(
        "/api/v1/counterparties",
        json={"name": "ООО Ромашка", "inn": "7701234567", "is_customer": True},
    )
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == "ООО Ромашка"
    assert body["is_customer"] is True
    assert body["is_local_supplier"] is False
    assert body["source"] == "manual"

    listed = client.get("/api/v1/counterparties").json()
    assert [row["name"] for row in listed] == ["ООО Ромашка"]
    assert [row["name"] for row in client.get("/api/v1/counterparties?role=customer").json()] == [
        "ООО Ромашка"
    ]
    assert client.get("/api/v1/counterparties?role=local_supplier").json() == []


def test_duplicate_counterparty_name_is_rejected(client: TestClient, login) -> None:
    login("sales")
    client.post("/api/v1/counterparties", json={"name": "ООО  Ромашка"})
    again = client.post("/api/v1/counterparties", json={"name": "ооо ромашка"})
    assert again.status_code == 409
    assert "уже есть" in again.json()["detail"]


def test_counterparty_can_become_supplier_and_be_deactivated(client: TestClient, login) -> None:
    login("sales")
    created = client.post("/api/v1/counterparties", json={"name": "Комус"}).json()
    updated = client.patch(
        f"/api/v1/counterparties/{created['id']}",
        json={"is_local_supplier": True, "is_active": False},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["is_local_supplier"] is True
    assert updated.json()["is_active"] is False

    assert client.get("/api/v1/counterparties").json() == []
    assert len(client.get("/api/v1/counterparties?include_inactive=true").json()) == 1
    assert len(client.get("/api/v1/counterparties?role=local_supplier").json()) == 0


def test_unknown_counterparty_role_is_rejected(client: TestClient) -> None:
    response = client.get("/api/v1/counterparties?role=unknown")
    assert response.status_code == 400


def test_product_can_be_created_and_edited(client: TestClient, login) -> None:
    login("sales")
    created = client.post(
        "/api/v1/products",
        json={"code": "ТОВ900", "name": "Краска белая", "kind": "material", "unit": "кг"},
    )
    assert created.status_code == 201, created.text
    product_id = created.json()["id"]
    assert created.json()["source"] == "manual"

    duplicate = client.post(
        "/api/v1/products", json={"code": "ТОВ900", "name": "Дубль", "unit": "шт"}
    )
    assert duplicate.status_code == 409

    updated = client.patch(
        f"/api/v1/products/{product_id}",
        json={"name": "Краска белая 20 кг", "kind": "finished"},
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Краска белая 20 кг"
    assert updated.json()["kind"] == "finished"


def test_unknown_product_kind_is_rejected(client: TestClient, login) -> None:
    login("sales")
    response = client.post(
        "/api/v1/products", json={"code": "ТОВ901", "name": "Мусор", "kind": "unknown"}
    )
    assert response.status_code == 400
    assert "Вид номенклатуры" in response.json()["detail"]


def test_import_manager_cannot_edit_directories(client: TestClient, login) -> None:
    login("import")
    assert client.post("/api/v1/counterparties", json={"name": "ООО Поздний"}).status_code == 403
    assert (
        client.post("/api/v1/products", json={"code": "ТОВ902", "name": "Поздний"}).status_code
        == 403
    )
    # Читать справочники можно всем, кто вошёл.
    assert client.get("/api/v1/counterparties").status_code == 200
    assert client.get("/api/v1/products").status_code == 200


def test_purchase_director_can_edit_directories(client: TestClient, login) -> None:
    login("purchase")
    assert client.post("/api/v1/counterparties", json={"name": "Закупки ООО"}).status_code == 201
