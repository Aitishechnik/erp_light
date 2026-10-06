"""Тестовый контур: работаем ТОЛЬКО с erp_lite_test из TEST_DATABASE_URL.

Никогда не подставлять сюда базу другого проекта.
"""

from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

import app.models  # noqa: F401 — регистрирует таблицы в Base.metadata
from app.config import get_settings
from app.db import Base, get_db
from app.main import create_app


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
def client(engine: Engine) -> Iterator[TestClient]:
    factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)

    def override_get_db() -> Iterator[Session]:
        db = factory()
        try:
            yield db
        finally:
            db.close()

    application = create_app(verify_db=False)
    application.dependency_overrides[get_db] = override_get_db
    with TestClient(application) as test_client:
        yield test_client
