"""Текущие остатки по партиям с себестоимостью."""

from fastapi import APIRouter

from app.api.deps import DbSession
from app.schemas.domain import StockRowOut
from app.services.batch_service import stock_rows

router = APIRouter(tags=["stock"])


@router.get("/stock", response_model=list[StockRowOut])
def get_stock(db: DbSession) -> list[StockRowOut]:
    return stock_rows(db)
