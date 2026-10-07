"""Текущие остатки по партиям с себестоимостью. Доступ — любому вошедшему."""

from fastapi import APIRouter

from app.api.deps import CurrentUser, DbSession
from app.schemas.domain import StockRowOut
from app.services.batch_service import stock_rows

router = APIRouter(tags=["stock"])


@router.get("/stock", response_model=list[StockRowOut])
def get_stock(user: CurrentUser, db: DbSession) -> list[StockRowOut]:
    return stock_rows(db)
