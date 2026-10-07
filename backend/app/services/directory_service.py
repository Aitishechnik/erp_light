"""Справочники: клиенты и номенклатура — ручное заведение и правка.

Читать справочники может любой вошедший, менять — продажи, коммерция и закупки.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.auth import (
    ROLE_COMMERCIAL_DIRECTOR,
    ROLE_PURCHASE_DIRECTOR,
    ROLE_SALES_MANAGER,
)
from app.models.clients import Client
from app.models.domain import PRODUCT_KINDS, Product
from app.schemas.clients import ClientIn, ClientUpdate
from app.schemas.domain import ProductIn, ProductUpdate

# Кто заводит и правит справочники.
DIRECTORY_WRITE_ROLES = (ROLE_SALES_MANAGER, ROLE_COMMERCIAL_DIRECTOR, ROLE_PURCHASE_DIRECTOR)


class DirectoryError(Exception):
    """Нарушение правил справочника; переносится в HTTP-ответ."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ── Клиенты ────────────────────────────────────────────────────────────────


def list_clients(db: Session, *, include_inactive: bool = False) -> list[Client]:
    statement = select(Client).order_by(Client.name)
    if not include_inactive:
        statement = statement.where(Client.is_active.is_(True))
    return list(db.execute(statement).scalars().all())


def get_client(db: Session, client_id: uuid.UUID) -> Client:
    client = db.get(Client, client_id)
    if client is None:
        raise DirectoryError("Клиент не найден", status_code=404)
    return client


def create_client(db: Session, payload: ClientIn) -> Client:
    name = payload.name.strip()
    if not name:
        raise DirectoryError("Укажите наименование клиента")
    exists = db.execute(select(Client).where(Client.name == name)).scalars().one_or_none()
    if exists is not None:
        raise DirectoryError(f"Клиент «{name}» уже есть в справочнике", status_code=409)
    client = Client(name=name, inn=payload.inn, note=payload.note)
    db.add(client)
    try:
        db.commit()
    except IntegrityError as exc:  # гонка двух одновременных созданий
        db.rollback()
        raise DirectoryError(f"Клиент «{name}» уже есть в справочнике", status_code=409) from exc
    db.refresh(client)
    return client


def update_client(db: Session, client_id: uuid.UUID, payload: ClientUpdate) -> Client:
    client = get_client(db, client_id)
    data = payload.model_dump(exclude_unset=True)
    if "name" in data and data["name"] is not None:
        name = str(data["name"]).strip()
        if not name:
            raise DirectoryError("Наименование клиента не может быть пустым")
        twin = db.execute(select(Client).where(Client.name == name)).scalars().one_or_none()
        if twin is not None and twin.id != client.id:
            raise DirectoryError(f"Клиент «{name}» уже есть в справочнике", status_code=409)
        data["name"] = name
    for field, value in data.items():
        setattr(client, field, value)
    db.commit()
    db.refresh(client)
    return client


# ── Номенклатура ───────────────────────────────────────────────────────────


def list_products(db: Session, *, kind: str | None = None) -> list[Product]:
    statement = select(Product).order_by(Product.code)
    if kind:
        statement = statement.where(Product.kind == kind)
    return list(db.execute(statement).scalars().all())


def get_product(db: Session, product_id: uuid.UUID) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise DirectoryError("Номенклатура не найдена", status_code=404)
    return product


def _check_kind(kind: str) -> None:
    if kind not in PRODUCT_KINDS:
        raise DirectoryError("Вид номенклатуры: goods (товар) или material (материал)")


def create_product(db: Session, payload: ProductIn) -> Product:
    code = payload.code.strip()
    if not code:
        raise DirectoryError("Укажите код (артикул)")
    _check_kind(payload.kind)
    exists = db.execute(select(Product).where(Product.code == code)).scalars().one_or_none()
    if exists is not None:
        raise DirectoryError(f"Номенклатура с кодом «{code}» уже есть", status_code=409)
    product = Product(
        code=code,
        name=payload.name.strip(),
        kind=payload.kind,
        unit=payload.unit.strip(),
    )
    db.add(product)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DirectoryError(f"Номенклатура с кодом «{code}» уже есть", status_code=409) from exc
    db.refresh(product)
    return product


def update_product(db: Session, product_id: uuid.UUID, payload: ProductUpdate) -> Product:
    product = get_product(db, product_id)
    data = payload.model_dump(exclude_unset=True)
    if data.get("kind") is not None:
        _check_kind(str(data["kind"]))
    if data.get("name") is not None:
        data["name"] = str(data["name"]).strip()
    if data.get("unit") is not None:
        data["unit"] = str(data["unit"]).strip()
    for field, value in data.items():
        setattr(product, field, value)
    db.commit()
    db.refresh(product)
    return product
