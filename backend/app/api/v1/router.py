"""Сборка v1 API."""

from fastapi import APIRouter

from app.api.v1 import (
    annual_sales_plans,
    auth,
    batches,
    counterparties,
    countries,
    health,
    imports,
    products,
    purchase_plans,
    rates,
    sales_plan_corrections,
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
api_router.include_router(countries.router)
api_router.include_router(imports.router)
api_router.include_router(rates.router)
api_router.include_router(batches.router)
api_router.include_router(stock.router)
api_router.include_router(sales_plans.router)
api_router.include_router(annual_sales_plans.router)
api_router.include_router(sales_plan_corrections.router)
api_router.include_router(purchase_plans.router)
