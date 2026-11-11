"""Точка входа FastAPI."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from app.api.v1.router import api_router
from app.config import get_settings
from app.db import SessionLocal, engine
from app.services import currency_service

logger = logging.getLogger("erp_lite")

# Незакрытая часть валютных инвойсов оценивается по последнему курсу, поэтому
# курсы обновляем сами — при старте и раз в час. Экран читает только то, что уже
# сохранено: сеть на пути чтения растягивала календарь на секунды, когда ЦБ
# недоступен, и делала по запросу на каждое поступление.
RATES_REFRESH_SECONDS = 3600


def refresh_rates_once() -> None:
    """Обновить курсы валют поступлений; отказ ЦБ пишем в лог с причиной."""
    try:
        with SessionLocal() as session:
            refreshed = currency_service.refresh_used_rates(session)
        if refreshed:
            logger.info("Курсы ЦБ обновлены: %s", ", ".join(sorted(refreshed)))
        else:
            logger.info("Курсы ЦБ: в поступлениях нет валют, кроме рубля")
    except Exception:  # noqa: BLE001 — фоновая задача не должна ронять приложение
        logger.warning(
            "Не удалось обновить курсы ЦБ — экран покажет сохранённые курсы", exc_info=True
        )


async def _rates_refresh_loop() -> None:
    while True:
        # Сеть и БД — в отдельном потоке: пока ЦБ отвечает, приложение обслуживает запросы.
        await asyncio.to_thread(refresh_rates_once)
        await asyncio.sleep(RATES_REFRESH_SECONDS)


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
        task: asyncio.Task[None] | None = None
        if verify_db:
            check_db()
            task = asyncio.create_task(_rates_refresh_loop())
        yield
        if task is not None:
            task.cancel()

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
