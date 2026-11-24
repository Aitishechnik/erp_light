"""Администратор, сотрудники и конструктор прав."""

from fastapi.testclient import TestClient

from app.services.auth import hash_password, verify_password


def _create(client: TestClient, **overrides: str) -> dict[str, object]:
    payload: dict[str, str] = {
        "login": "valeri_serg",
        "full_name": "Валерий Сергеевич",
        "password": "3f3H!df9",
        "role": "commercial_director",
    }
    payload.update(overrides)
    response = client.post("/api/v1/admin/users", json=payload)
    assert response.status_code == 201, response.text
    body: dict[str, object] = response.json()
    return body


def test_admin_is_separate_role_with_full_access(client: TestClient, login) -> None:
    login("admin")
    me = client.get("/api/v1/auth/me")
    assert me.status_code == 200
    body = me.json()
    assert body["role"] == "admin"
    assert body["role_title"] == "Администратор"
    assert body["is_admin"] is True
    # Интерфейсу достаточно is_admin, но полный профиль тоже приходит.
    assert body["permissions"]["sales_plans"]["scope"] == "all"

    for path in (
        "/api/v1/stock",
        "/api/v1/users",
        "/api/v1/purchase-plans?year=2027",
        "/api/v1/access",
        "/api/v1/admin/users",
        "/api/v1/admin/audit",
    ):
        assert client.get(path).status_code == 200, path


def test_executive_director_is_not_admin_anymore(client: TestClient, login) -> None:
    login("executive")
    assert client.get("/api/v1/admin/users").status_code == 403
    assert client.get("/api/v1/access").status_code == 403
    assert client.get("/api/v1/admin/audit").status_code == 403
    # Бизнес-права при этом на месте: годовой план и итоги месяца.
    assert client.get("/api/v1/annual-sales-plans?year=2027").status_code == 200


def test_access_constructor_lists_six_levels(client: TestClient, login) -> None:
    login("admin")
    body = client.get("/api/v1/access").json()
    levels = {row["key"] for row in body["levels"]}
    assert "admin" not in levels
    assert levels == {
        "sales_manager",
        "sales_assistant",
        "commercial_director",
        "purchase_director",
        "import_manager",
        "executive_director",
    }
    sales = next(row for row in body["levels"] if row["key"] == "sales_manager")
    assert sales["rights"]["sales_plans"]["scope"] == "own"
    assert "approve" not in sales["rights"]["sales_plans"]["actions"]
    blocks = {row["key"]: row for row in body["blocks"]}
    assert blocks["sales_plans"]["scoped"] is True
    assert blocks["users"]["scoped"] is False


def test_admin_creates_user_who_can_log_in(client: TestClient, login, logout) -> None:
    login("admin")
    created = _create(client)
    assert created["role"] == "commercial_director"
    assert created["is_admin"] is False

    logout()
    login("valeri_serg", "3f3H!df9")
    me = client.get("/api/v1/auth/me").json()
    assert me["full_name"] == "Валерий Сергеевич"
    assert me["role"] == "commercial_director"
    assert me["is_admin"] is False
    # Права уровня пришли вместе с пользователем: по ним строится меню.
    assert "approve" in me["permissions"]["sales_plans"]["actions"]
    assert me["permissions"]["sales_plans"]["scope"] == "all"


def test_create_user_rules(client: TestClient, login) -> None:
    login("admin")
    _create(client)
    duplicate = client.post(
        "/api/v1/admin/users",
        json={
            "login": "VALERI_SERG",
            "full_name": "Другой",
            "password": "12345678",
            "role": "sales_manager",
        },
    )
    assert duplicate.status_code == 409

    short = client.post(
        "/api/v1/admin/users",
        json={
            "login": "short",
            "full_name": "Короткий пароль",
            "password": "1234567",
            "role": "sales_manager",
        },
    )
    assert short.status_code == 422

    admin_role = client.post(
        "/api/v1/admin/users",
        json={
            "login": "second_admin",
            "full_name": "Второй админ",
            "password": "12345678",
            "role": "admin",
        },
    )
    assert admin_role.status_code == 400
    assert "администратора" in admin_role.json()["detail"]


def test_admin_account_cannot_be_blocked_or_demoted(client: TestClient, login) -> None:
    login("admin")
    me = client.get("/api/v1/auth/me").json()
    response = client.patch(f"/api/v1/admin/users/{me['id']}", json={"is_active": False})
    assert response.status_code == 403
    assert "администратора" in response.json()["detail"]


def test_admin_changes_own_password(client: TestClient, login, logout) -> None:
    login("admin")
    me = client.get("/api/v1/auth/me").json()
    response = client.post(
        f"/api/v1/admin/users/{me['id']}/password", json={"password": "new-password-1"}
    )
    assert response.status_code == 200
    logout()
    login("admin", "new-password-1")


def test_deactivated_user_loses_access(client: TestClient, login, logout) -> None:
    login("admin")
    created = _create(client, login="blocked", full_name="Заблокированный")
    assert created["is_active"] is True
    response = client.patch(f"/api/v1/admin/users/{created['id']}", json={"is_active": False})
    assert response.status_code == 200
    assert response.json()["is_active"] is False
    logout()
    denied = client.post("/api/v1/auth/login", json={"login": "blocked", "password": "3f3H!df9"})
    assert denied.status_code == 401


def test_level_rights_apply_to_all_users_of_level(client: TestClient, login) -> None:
    login("admin")
    # Менеджеру по продажам оставляем только просмотр своих планов.
    saved = client.put(
        "/api/v1/access/sales_manager",
        json={"rights": {"sales_plans": {"actions": ["view"], "scope": "own"}}},
    )
    assert saved.status_code == 200, saved.text

    login("sales")
    assert client.get("/api/v1/sales-plans").status_code == 200
    # Создавать план больше нельзя: кнопка скрыта, сервер тоже откажет.
    create = client.post("/api/v1/sales-plans", json={"year": 2027})
    assert create.status_code == 403

    login("admin")
    client.put(
        "/api/v1/access/sales_manager",
        json={"rights": {"sales_plans": {"actions": [], "scope": "own"}}},
    )
    login("sales")
    assert client.get("/api/v1/sales-plans").status_code == 403


def test_scope_change_hides_other_managers_plans(client: TestClient, login) -> None:
    login("admin")
    client.put(
        "/api/v1/access/commercial_director",
        json={"rights": {"sales_plans": {"actions": ["view"], "scope": "own"}}},
    )
    login("commercial")
    body = client.get("/api/v1/sales-plans").json()
    # «Только свои» для директора — это планы, где он менеджер; таких нет.
    assert body == []
    me = client.get("/api/v1/auth/me").json()
    assert me["permissions"]["sales_plans"]["scope"] == "own"


def test_admin_actions_have_their_own_journal(client: TestClient, login) -> None:
    login("admin")
    created = _create(client)
    client.patch(f"/api/v1/admin/users/{created['id']}", json={"full_name": "Валерий С."})

    admin_actions = [row["action"] for row in client.get("/api/v1/admin/audit").json()]
    assert "user.created" in admin_actions
    assert "user.updated" in admin_actions

    login("commercial")
    regular = client.get("/api/v1/audit").json()
    assert all(row["actor_role_title"] != "Администратор" for row in regular)
    assert "user.created" not in [row["action"] for row in regular]


def test_password_is_stored_as_hash() -> None:
    stored = hash_password("3f3H!df9")
    assert "3f3H!df9" not in stored
    assert verify_password("3f3H!df9", stored)
    assert not verify_password("другой", stored)
