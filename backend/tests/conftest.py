"""Тестовый контур: работаем ТОЛЬКО с erp_lite_test из TEST_DATABASE_URL.

Никогда не подставлять сюда базу другого проекта.
"""

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401 — регистрирует таблицы в Base.metadata
from app.config import get_settings
from app.db import Base, get_db
from app.main import create_app
from app.models.counterparties import Counterparty
from app.models.countries import Country
from app.models.domain import Product
from app.services.auth import seed_demo_users
from tests.helpers import put_batch

# Пароль демо-пользователей в тестах; роли — по логину (sales, commercial, ...).
DEMO_PASSWORD = "test-password"


@pytest.fixture(scope="session")
def engine() -> Iterator[Engine]:
    settings = get_settings()
    assert settings.test_database_url, "TEST_DATABASE_URL не задан в .env"
    eng = create_engine(settings.test_database_url, pool_pre_ping=True, future=True)
    Base.metadata.drop_all(eng)
    Base.metadata.create_all(eng)
    yield eng
    Base.metadata.drop_all(eng)
    eng.dispose()


@pytest.fixture(autouse=True)
def _clean_tables(engine: Engine) -> Iterator[None]:
    """Перед каждым тестом — пустые таблицы."""
    with engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.execute(table.delete())
    yield


@pytest.fixture
def db_session(engine: Engine) -> Iterator[Session]:
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    session = factory()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture
def users(engine: Engine) -> None:
    """Демо-пользователи всех пяти ролей с известным паролем."""
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with factory() as session:
        seed_demo_users(session, DEMO_PASSWORD)


def _build_client(engine: Engine) -> TestClient:
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db() -> Iterator[Session]:
        db = factory()
        try:
            yield db
        finally:
            db.close()

    application = create_app(verify_db=False)
    application.dependency_overrides[get_db] = override_get_db
    return TestClient(application)


@pytest.fixture
def catalog(db_session: Session) -> dict[str, Any]:
    finished = Product(code="FIN-1", name="Смесь ореховая", kind="finished", unit="шт")
    finished2 = Product(code="FIN-2", name="Финики", kind="finished", unit="кг")
    raw = Product(code="RAW-1", name="Арахис", kind="raw", unit="кг")
    raw2 = Product(code="RAW-2", name="Кокос", kind="raw", unit="кг")
    material = Product(code="MAT-1", name="Банка 500 г", kind="material", unit="шт")
    inactive_raw = Product(
        code="RAW-3", name="Старое сырьё", kind="raw", unit="кг", is_active=False
    )
    customer = Counterparty(name="ООО Ромашка", name_key="ооо ромашка", is_customer=True)
    supplier = Counterparty(name="ООО Импорт", name_key="ооо импорт", is_import_supplier=True)
    local = Counterparty(name="ООО Локальный", name_key="ооо локальный", is_local_supplier=True)
    thailand = Country(name="Таиланд", name_key="таиланд", delivery_days=90)
    china = Country(name="Китай", name_key="китай", delivery_days=65)
    fast = Country(name="Индия", name_key="индия", delivery_days=30)
    inactive_country = Country(
        name="Недоступная", name_key="недоступная", delivery_days=10, is_active=False
    )
    db_session.add_all(
        [
            finished,
            finished2,
            raw,
            raw2,
            material,
            inactive_raw,
            customer,
            supplier,
            local,
            thailand,
            china,
            fast,
            inactive_country,
        ]
    )
    db_session.commit()
    return {
        "fin": finished,
        "fin2": finished2,
        "raw": raw,
        "raw2": raw2,
        "material": material,
        "inactive_raw": inactive_raw,
        "customer": customer,
        "supplier": supplier,
        "local": local,
        "thailand": thailand,
        "china": china,
        "fast": fast,
        "inactive_country": inactive_country,
    }


@pytest.fixture
def client(engine: Engine, users: None) -> Iterator[TestClient]:
    """Клиент, вошедший как менеджер по закупкам (импорт)."""
    with _build_client(engine) as test_client:
        response = test_client.post(
            "/api/v1/auth/login", json={"login": "import", "password": DEMO_PASSWORD}
        )
        assert response.status_code == 200, response.text
        yield test_client


@pytest.fixture
def login(client: TestClient) -> Callable[[str], None]:
    """Сменить пользователя: login("commercial") — коммерческий директор."""

    def _login(login_name: str, password: str = DEMO_PASSWORD) -> None:
        response = client.post(
            "/api/v1/auth/login", json={"login": login_name, "password": password}
        )
        assert response.status_code == 200, response.text

    return _login


@pytest.fixture
def logout(client: TestClient) -> Callable[[], None]:
    def _logout() -> None:
        assert client.post("/api/v1/auth/logout").status_code == 204

    return _logout


@pytest.fixture
def make_batch(client: TestClient) -> Callable[..., dict[str, Any]]:
    """Завести поступление как в жизни: черновик из 1С, затем правка карточки.

    Эндпоинта создания поступления больше нет — тесты идут тем же путём, что и
    приложение: выгрузка шапки, затем ``PUT /batches/{id}`` со строками.
    """

    def _make(payload: dict[str, Any]) -> dict[str, Any]:
        body: dict[str, Any] = put_batch(client, payload)
        return body

    return _make
