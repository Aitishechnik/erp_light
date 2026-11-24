"""Текущие остатки по партиям с себестоимостью. Доступ — любому вошедшему."""

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.deps import DbSession, require_perm
from app.models.auth import User
from app.schemas.domain import StockRowOut
from app.services.batch_service import stock_rows

router = APIRouter(tags=["stock"])

Viewer = Annotated[User, Depends(require_perm("stock", "view"))]


@router.get("/stock", response_model=list[StockRowOut])
def get_stock(user: Viewer, db: DbSession) -> list[StockRowOut]:
    return stock_rows(db)
