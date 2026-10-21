"""Справочник стран: название, срок доставки, роли и дубли."""

from typing import Any

from fastapi.testclient import TestClient


def _create(client: TestClient, name: str = "Таиланд", days: int = 90) -> Any:
    return client.post("/api/v1/countries", json={"name": name, "delivery_days": days})


def test_country_crud_and_duplicates(client: TestClient, login) -> None:
    login("purchase")
    created = _create(client)
    assert created.status_code == 201, created.text
    body = created.json()
    assert body["name"] == "Таиланд"
    assert body["delivery_days"] == 90
    assert body["is_active"] is True

    duplicate = _create(client, " таиланд ", 65)
    assert duplicate.status_code == 409, duplicate.text
    assert "уже есть" in duplicate.json()["detail"]

    listed = client.get("/api/v1/countries")
    assert listed.status_code == 200
    assert [row["name"] for row in listed.json()] == ["Таиланд"]

    updated = client.patch(
        f"/api/v1/countries/{body['id']}", json={"name": "Китай", "delivery_days": 65}
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Китай"
    assert updated.json()["delivery_days"] == 65

    off = client.patch(f"/api/v1/countries/{body['id']}", json={"is_active": False})
    assert off.status_code == 200, off.text
    assert off.json()["is_active"] is False
    assert client.get("/api/v1/countries").json() == []
    assert len(client.get("/api/v1/countries", params={"include_inactive": True}).json()) == 1


def test_country_validation(client: TestClient, login) -> None:
    login("purchase")
    assert _create(client, "Страна", 0).status_code == 422
    assert _create(client, "Страна", 366).status_code == 422
    assert _create(client, "   ", 30).status_code == 400
    assert _create(client, "", 30).status_code == 422


def test_only_purchase_director_edits_countries(client: TestClient, login) -> None:
    login("import")
    assert client.get("/api/v1/countries").status_code == 200
    assert _create(client).status_code == 403

    login("sales")
    assert client.get("/api/v1/countries").status_code == 200
    assert _create(client).status_code == 403

    login("executive")
    assert client.get("/api/v1/countries").status_code == 200
    assert _create(client).status_code == 403

    login("purchase")
    created = _create(client)
    assert created.status_code == 201
    country_id = created.json()["id"]

    login("import")
    assert (
        client.patch(f"/api/v1/countries/{country_id}", json={"delivery_days": 10}).status_code
        == 403
    )
