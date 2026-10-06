"""Сборка v1 API."""

from fastapi import APIRouter

from app.api.v1 import batches, health, products, stock

api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(products.router)
api_router.include_router(batches.router)
api_router.include_router(stock.router)
