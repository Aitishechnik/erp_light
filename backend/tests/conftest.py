"""Тестовый контур: работаем ТОЛЬКО с erp_lite_test из TEST_DATABASE_URL.

Никогда не подставлять сюда базу другого проекта.
"""

from collections.abc import Callable, Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401 — регистрирует таблицы в Base.metadata
from app.config import get_settings
from app.db import Base, get_db
from app.main import create_app
from app.services.auth import seed_demo_users

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
