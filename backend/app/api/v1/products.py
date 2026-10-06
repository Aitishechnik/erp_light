"""Номенклатура."""

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.api.deps import DbSession
from app.models.domain import Product
from app.schemas.domain import ProductOut

router = APIRouter(tags=["products"])


@router.get("/products", response_model=list[ProductOut])
def list_products(
    db: DbSession,
    kind: str | None = Query(default=None, description="goods | material"),
) -> list[Product]:
    stmt = select(Product).order_by(Product.code)
    if kind:
        stmt = stmt.where(Product.kind == kind)
    return list(db.execute(stmt).scalars().all())
