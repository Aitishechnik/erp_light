"""Модели домена. Импортируются здесь, чтобы alembic и create_all их видели."""

from app.models.auth import (
    ROLE_COMMERCIAL_DIRECTOR,
    ROLE_EXECUTIVE_DIRECTOR,
    ROLE_IMPORT_MANAGER,
    ROLE_PURCHASE_DIRECTOR,
    ROLE_SALES_MANAGER,
    ROLE_TITLES,
    ROLES,
    AuthSession,
    User,
)
from app.models.domain import (
    BATCH_TYPES,
    PRODUCT_KINDS,
    SOURCES,
    Batch,
    BatchExpense,
    BatchItem,
    ImportSession,
    Product,
    StockSnapshot,
)
from app.models.planning import (
    SALES_PLAN_STATUS_TITLES,
    SALES_PLAN_STATUSES,
    SalesPlan,
    SalesPlanItem,
)

__all__ = [
    "BATCH_TYPES",
    "PRODUCT_KINDS",
    "ROLES",
    "ROLE_COMMERCIAL_DIRECTOR",
    "ROLE_EXECUTIVE_DIRECTOR",
    "ROLE_IMPORT_MANAGER",
    "ROLE_PURCHASE_DIRECTOR",
    "ROLE_SALES_MANAGER",
    "ROLE_TITLES",
    "SALES_PLAN_STATUSES",
    "SALES_PLAN_STATUS_TITLES",
    "SOURCES",
    "AuthSession",
    "Batch",
    "BatchExpense",
    "BatchItem",
    "ImportSession",
    "Product",
    "SalesPlan",
    "SalesPlanItem",
    "StockSnapshot",
    "User",
]
