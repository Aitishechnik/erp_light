"""Точка входа FastAPI."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.v1.router import api_router
from app.config import get_settings
from app.db import engine


def check_db() -> None:
    """Явная ошибка при недоступной БД (лучше упасть на старте, чем молча)."""
    try:
        with engine.connect() as conn:
            conn.execute(text("select 1"))
    except Exception as exc:  # noqa: BLE001 — нужен любой отказ соединения
        raise RuntimeError(
            "Нет соединения с БД проекта erp_lite. Проверьте .env и поднимите "
            "контейнер: docker compose up -d --wait"
        ) from exc


def create_app(*, verify_db: bool = True) -> FastAPI:
    settings = get_settings()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        if verify_db:
            check_db()
        yield

    app = FastAPI(title="erp_lite API", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[
            f"http://127.0.0.1:{settings.app_port}",
            f"http://localhost:{settings.app_port}",
        ],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.include_router(api_router, prefix="/api/v1")

    @app.get("/healthz", tags=["health"])
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
