"""Справочники: контрагенты и номенклатура — ручное заведение и правка.

Читать справочники может любой вошедший, менять — продажи, коммерция, закупки
и исполнительный директор (администратор). Основное наполнение приходит
загрузкой выгрузок 1С (см. import_service).
"""

from __future__ import annotations

import uuid

from sqlalchemy import ColumnElement, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.auth import (
    ROLE_COMMERCIAL_DIRECTOR,
    ROLE_EXECUTIVE_DIRECTOR,
    ROLE_PURCHASE_DIRECTOR,
    ROLE_SALES_MANAGER,
    User,
)
from app.models.counterparties import Counterparty, name_key
from app.models.domain import PRODUCT_KINDS, Product
from app.schemas.counterparties import CounterpartyIn, CounterpartyUpdate
from app.schemas.domain import ProductIn, ProductUpdate

# Кто заводит и правит справочники. Исполнительный директор — как администратор.
DIRECTORY_WRITE_ROLES = (
    ROLE_SALES_MANAGER,
    ROLE_COMMERCIAL_DIRECTOR,
    ROLE_PURCHASE_DIRECTOR,
    ROLE_EXECUTIVE_DIRECTOR,
)


class DirectoryError(Exception):
    """Нарушение правил справочника; переносится в HTTP-ответ."""

    def __init__(self, message: str, *, status_code: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


# ── Контрагенты ────────────────────────────────────────────────────────────


def list_counterparties(
    db: Session, *, role_field: str | None = None, include_inactive: bool = False
) -> list[Counterparty]:
    statement = select(Counterparty).order_by(Counterparty.name)
    if role_field is not None:
        statement = statement.where(getattr(Counterparty, role_field).is_(True))
    if not include_inactive:
        statement = statement.where(Counterparty.is_active.is_(True))
    return list(db.execute(statement).scalars().all())


def page_counterparties(
    db: Session,
    *,
    role_field: str | None = None,
    include_inactive: bool = False,
    search: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[Counterparty], int]:
    """Порция справочника и сколько всего нашлось — для кнопки «показать ещё».

    ``limit`` не задан — отдаём все строки, как раньше: так работает выбор
    контрагента в карточках, которому нужен полный список.
    """
    conditions: list[ColumnElement[bool]] = []
    if role_field is not None:
        conditions.append(getattr(Counterparty, role_field).is_(True))
    if not include_inactive:
        conditions.append(Counterparty.is_active.is_(True))
    needle = (search or "").strip()
    if needle:
        conditions.append(Counterparty.name.icontains(needle, autoescape=True))

    total = db.execute(
        select(func.count()).select_from(Counterparty).where(*conditions)
    ).scalar_one()
    statement = select(Counterparty).where(*conditions).order_by(Counterparty.name)
    if limit is not None:
        statement = statement.offset(offset).limit(limit)
    return list(db.execute(statement).scalars().all()), int(total)


def get_counterparty(db: Session, counterparty_id: uuid.UUID) -> Counterparty:
    row = db.get(Counterparty, counterparty_id)
    if row is None:
        raise DirectoryError("Контрагент не найден", status_code=404)
    return row


def _check_manager(db: Session, manager_id: uuid.UUID | None) -> None:
    """Менеджер клиента — активный пользователь с ролью «менеджер по продажам»."""
    if manager_id is None:
        return
    manager = db.get(User, manager_id)
    if manager is None or manager.role != ROLE_SALES_MANAGER or not manager.is_active:
        raise DirectoryError("Менеджер не найден или у него другая роль")


def create_counterparty(db: Session, payload: CounterpartyIn) -> Counterparty:
    name = " ".join(payload.name.split()).strip()
    if not name:
        raise DirectoryError("Укажите наименование контрагента")
    _check_manager(db, payload.manager_id)
    key = name_key(name)
    exists = (
        db.execute(select(Counterparty).where(Counterparty.name_key == key)).scalars().one_or_none()
    )
    if exists is not None:
        raise DirectoryError(f"Контрагент «{name}» уже есть в справочнике", status_code=409)
    counterparty = Counterparty(
        name=name,
        name_key=key,
        inn=payload.inn,
        note=payload.note,
        is_customer=payload.is_customer,
        is_local_supplier=payload.is_local_supplier,
        is_import_supplier=payload.is_import_supplier,
        manager_id=payload.manager_id,
        source="manual",
    )
    db.add(counterparty)
    try:
        db.commit()
    except IntegrityError as exc:  # гонка двух одновременных созданий
        db.rollback()
        raise DirectoryError(
            f"Контрагент «{name}» уже есть в справочнике", status_code=409
        ) from exc
    db.refresh(counterparty)
    return counterparty


def update_counterparty(
    db: Session, counterparty_id: uuid.UUID, payload: CounterpartyUpdate
) -> Counterparty:
    counterparty = get_counterparty(db, counterparty_id)
    data = payload.model_dump(exclude_unset=True)
    if "manager_id" in data:
        _check_manager(db, data["manager_id"])
    if data.get("name") is not None:
        name = " ".join(str(data["name"]).split()).strip()
        if not name:
            raise DirectoryError("Наименование контрагента не может быть пустым")
        key = name_key(name)
        twin = (
            db.execute(select(Counterparty).where(Counterparty.name_key == key))
            .scalars()
            .one_or_none()
        )
        if twin is not None and twin.id != counterparty.id:
            raise DirectoryError(f"Контрагент «{name}» уже есть в справочнике", status_code=409)
        data["name"] = name
        data["name_key"] = key
    for field, value in data.items():
        setattr(counterparty, field, value)
    db.commit()
    db.refresh(counterparty)
    return counterparty


# ── Номенклатура ───────────────────────────────────────────────────────────


def list_products(
    db: Session, *, kind: str | None = None, kinds: list[str] | None = None
) -> list[Product]:
    """Номенклатура по коду. ``kinds`` — несколько видов сразу (списки выбора)."""
    statement = select(Product).order_by(Product.code)
    selected = kinds if kinds is not None else ([kind] if kind else None)
    if selected:
        statement = statement.where(Product.kind.in_(selected))
    return list(db.execute(statement).scalars().all())


def page_products(
    db: Session,
    *,
    kinds: list[str] | None = None,
    include_inactive: bool = True,
    search: str | None = None,
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[Product], int]:
    """Порция номенклатуры и сколько всего нашлось.

    Поиск идёт по коду и наименованию на сервере: иначе он видел бы только
    первые загруженные строки. ``limit`` не задан — отдаём все строки, как
    раньше (списки выбора в планах и поступлениях).
    """
    conditions: list[ColumnElement[bool]] = []
    if kinds:
        conditions.append(Product.kind.in_(kinds))
    if not include_inactive:
        conditions.append(Product.is_active.is_(True))
    needle = (search or "").strip()
    if needle:
        conditions.append(
            or_(
                Product.code.icontains(needle, autoescape=True),
                Product.name.icontains(needle, autoescape=True),
            )
        )

    total = db.execute(select(func.count()).select_from(Product).where(*conditions)).scalar_one()
    statement = select(Product).where(*conditions).order_by(Product.code)
    if limit is not None:
        statement = statement.offset(offset).limit(limit)
    return list(db.execute(statement).scalars().all()), int(total)


def get_product(db: Session, product_id: uuid.UUID) -> Product:
    product = db.get(Product, product_id)
    if product is None:
        raise DirectoryError("Номенклатура не найдена", status_code=404)
    return product


def _check_kind(kind: str) -> None:
    if kind not in PRODUCT_KINDS:
        raise DirectoryError(
            "Вид номенклатуры: material (материалы), raw (сырьё) "
            "или finished (готовая продукция)"
        )


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
        source="manual",
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
