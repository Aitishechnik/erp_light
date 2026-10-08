"""Сборка v1 API."""

from fastapi import APIRouter

from app.api.v1 import (
    auth,
    batches,
    counterparties,
    health,
    imports,
    products,
    rates,
    sales_plans,
    stock,
    users,
)

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
api_router.include_router(products.router)
api_router.include_router(counterparties.router)
api_router.include_router(imports.router)
api_router.include_router(rates.router)
api_router.include_router(batches.router)
api_router.include_router(stock.router)
api_router.include_router(sales_plans.router)
