"""Позиции будущих периодов: планируем номенклатуру, которой ещё нет в 1С.

Будущая позиция — обычная карточка ``Product`` с признаком ``is_future``:
поэтому планы, корректировки, месячные планы и закупки ссылаются на неё
обычным ``product_id`` и не требуют отдельных веток. В обычную номенклатуру,
остатки и сопоставление продаж она не попадает (фильтр в списке продуктов).

Жизненный цикл: создать по названию → планировать → когда позиция появилась в
1С, привязать к реальной карточке. Привязка переносит все ссылки и удаляет
заглушку; отменить её нельзя, поэтому действие пишется в журнал.
"""

from __future__ import annotations

import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import func, or_, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.domain import FUTURE_PRODUCT_CODE_PREFIX, BatchItem, Product
from app.models.monthly_plans import (
    MonthlySalesPlan,
    MonthlySalesPlanEvent,
    MonthlySalesPlanItem,
)
from app.models.planning import (
    PurchasePlan,
    PurchasePlanItem,
    SalesPlan,
    SalesPlanCorrection,
    SalesPlanCorrectionItem,
    SalesPlanItem,
)
from app.models.sales import DeviationReason, ProductAlias, SalesFact
from app.schemas.domain import (
    FutureProductBindOut,
    FutureProductIn,
    FutureProductOut,
    FutureProductUpdate,
)
from app.services.directory_service import DirectoryError

OPEN_CORRECTION_STATUSES = ("draft", "on_review")


def _uuid(value: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(value))
    except (TypeError, ValueError):
        return None


def _require_future(db: Session, product_id: uuid.UUID) -> Product:
    product = db.get(Product, product_id)
    if product is None or not product.is_future:
        raise DirectoryError("Будущая позиция не найдена", status_code=404)
    return product


def _check_name(db: Session, name: str, *, exclude_id: uuid.UUID | None = None) -> str:
    """Имя будущей позиции не должно дублировать уже существующую карточку."""
    clean = name.strip()
    if not clean:
        raise DirectoryError("Укажите название позиции")
    existing = (
        db.execute(select(Product).where(func.lower(Product.name) == clean.lower()))
        .scalars()
        .first()
    )
    if existing is not None and existing.id != exclude_id:
        label = existing.name if existing.is_future else f"{existing.code} · {existing.name}"
        raise DirectoryError(f"Позиция «{label}» уже есть — выберите её в списке", status_code=409)
    return clean


def _generate_code(db: Session) -> str:
    for _ in range(5):
        code = FUTURE_PRODUCT_CODE_PREFIX + uuid.uuid4().hex[:6].upper()
        if db.scalar(select(Product.id).where(Product.code == code)) is None:
            return code
    raise DirectoryError("Не удалось подобрать код будущей позиции", status_code=500)


def _plan_usage(db: Session, product_ids: set[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
    """Планы и строки, где упомянута позиция: строки плана и состав черновиков."""
    usage: dict[uuid.UUID, dict[str, Any]] = {
        product_id: {"plan_ids": set(), "years": set(), "rows": 0, "pairs": set()}
        for product_id in product_ids
    }
    item_rows = db.execute(
        select(
            SalesPlanItem.product_id,
            SalesPlanItem.plan_id,
            SalesPlanItem.client_id,
            SalesPlan.year,
        )
        .join(SalesPlan, SalesPlan.id == SalesPlanItem.plan_id)
        .where(SalesPlanItem.product_id.in_(product_ids))
    ).all()
    for product_id, plan_id, client_id, year in item_rows:
        row = usage[product_id]
        row["plan_ids"].add(plan_id)
        row["years"].add(year)
        row["rows"] += 1
        row["pairs"].add((plan_id, client_id))

    draft_rows = db.execute(
        select(SalesPlan.id, SalesPlan.year, SalesPlan.draft_rows).where(
            SalesPlan.draft_rows.isnot(None)
        )
    ).all()
    for plan_id, year, rows in draft_rows:
        for draft in rows or []:
            product_id = _uuid(draft.get("product_id"))
            client_id = _uuid(draft.get("client_id"))
            if product_id not in usage or client_id is None:
                continue
            row = usage[product_id]
            row["plan_ids"].add(plan_id)
            row["years"].add(year)
            if (plan_id, client_id) not in row["pairs"]:
                row["pairs"].add((plan_id, client_id))
                row["rows"] += 1
    return usage


def _other_usage(db: Session, product_ids: set[uuid.UUID]) -> dict[uuid.UUID, dict[str, Any]]:
    """Корректировки, месячные планы и закупки: сколько ссылок и за какие годы."""
    usage: dict[uuid.UUID, dict[str, Any]] = {
        product_id: {"count": 0, "years": set()} for product_id in product_ids
    }

    corrections = db.execute(
        select(SalesPlanCorrectionItem.product_id, SalesPlan.year, func.count())
        .join(
            SalesPlanCorrection,
            SalesPlanCorrection.id == SalesPlanCorrectionItem.correction_id,
        )
        .join(SalesPlan, SalesPlan.id == SalesPlanCorrection.plan_id)
        .where(SalesPlanCorrectionItem.product_id.in_(product_ids))
        .group_by(SalesPlanCorrectionItem.product_id, SalesPlan.year)
    ).all()
    for product_id, year, count in corrections:
        usage[product_id]["count"] += count
        usage[product_id]["years"].add(year)

    monthly = db.execute(
        select(MonthlySalesPlanItem.product_id, MonthlySalesPlan.year, func.count())
        .join(MonthlySalesPlan, MonthlySalesPlan.id == MonthlySalesPlanItem.plan_id)
        .where(MonthlySalesPlanItem.product_id.in_(product_ids))
        .group_by(MonthlySalesPlanItem.product_id, MonthlySalesPlan.year)
    ).all()
    for product_id, year, count in monthly:
        usage[product_id]["count"] += count
        usage[product_id]["years"].add(year)

    purchases = db.execute(
        select(PurchasePlanItem.sales_product_id, PurchasePlan.year, func.count())
        .join(PurchasePlan, PurchasePlan.id == PurchasePlanItem.plan_id)
        .where(PurchasePlanItem.sales_product_id.in_(product_ids))
        .group_by(PurchasePlanItem.sales_product_id, PurchasePlan.year)
    ).all()
    for product_id, year, count in purchases:
        usage[product_id]["count"] += count
        usage[product_id]["years"].add(year)

    purchases_as_raw = db.execute(
        select(PurchasePlanItem.product_id, PurchasePlan.year, func.count())
        .join(PurchasePlan, PurchasePlan.id == PurchasePlanItem.plan_id)
        .where(PurchasePlanItem.product_id.in_(product_ids))
        .group_by(PurchasePlanItem.product_id, PurchasePlan.year)
    ).all()
    for product_id, year, count in purchases_as_raw:
        usage[product_id]["count"] += count
        usage[product_id]["years"].add(year)

    for column in (
        BatchItem.product_id,
        SalesFact.product_id,
        ProductAlias.product_id,
        DeviationReason.product_id,
        MonthlySalesPlanEvent.product_id,
    ):
        rows = db.execute(
            select(column, func.count()).where(column.in_(product_ids)).group_by(column)
        ).all()
        for product_id, count in rows:
            usage[product_id]["count"] += count
    return usage


def list_future_products(db: Session) -> list[FutureProductOut]:
    """Список будущих позиций с использованием в планах и документах."""
    products = (
        db.execute(select(Product).where(Product.is_future.is_(True)).order_by(Product.name))
        .scalars()
        .all()
    )
    if not products:
        return []
    product_ids = {product.id for product in products}
    plans = _plan_usage(db, product_ids)
    others = _other_usage(db, product_ids)
    result: list[FutureProductOut] = []
    for product in products:
        plan = plans[product.id]
        other = others[product.id]
        result.append(
            FutureProductOut(
                id=product.id,
                name=product.name,
                unit=product.unit,
                kind=product.kind,
                created_at=product.created_at,
                plans_count=len(plan["plan_ids"]),
                rows_count=plan["rows"],
                other_documents=other["count"],
                years=sorted(plan["years"] | other["years"]),
                delete_allowed=not any(_references(db, product.id).values()),
            )
        )
    return result


def create_future_product(db: Session, payload: FutureProductIn) -> Product:
    """Завести позицию по названию: код 1С появится только при привязке."""
    name = _check_name(db, payload.name)
    product = Product(
        code=_generate_code(db),
        name=name,
        kind="finished",
        unit=payload.unit,
        source="manual",
        is_future=True,
    )
    db.add(product)
    try:
        db.commit()
    except IntegrityError as exc:  # pragma: no cover - защита от гонки по коду
        db.rollback()
        raise DirectoryError(
            "Не удалось завести будущую позицию — повторите", status_code=409
        ) from exc
    db.refresh(product)
    return product


def update_future_product(
    db: Session, product_id: uuid.UUID, payload: FutureProductUpdate
) -> Product:
    product = _require_future(db, product_id)
    data = payload.model_dump(exclude_unset=True)
    if data.get("name") is not None:
        product.name = _check_name(db, str(data["name"]), exclude_id=product.id)
    if data.get("unit") is not None:
        product.unit = str(data["unit"])
    db.commit()
    db.refresh(product)
    return product


def _references(db: Session, product_id: uuid.UUID) -> dict[str, int]:
    """Все живые ссылки на позицию. Состав черновика без количеств сюда не входит."""
    return {
        "plan_rows": db.scalar(
            select(func.count())
            .select_from(SalesPlanItem)
            .where(SalesPlanItem.product_id == product_id)
        )
        or 0,
        "corrections": db.scalar(
            select(func.count())
            .select_from(SalesPlanCorrectionItem)
            .where(SalesPlanCorrectionItem.product_id == product_id)
        )
        or 0,
        "monthly": db.scalar(
            select(func.count())
            .select_from(MonthlySalesPlanItem)
            .where(MonthlySalesPlanItem.product_id == product_id)
        )
        or 0,
        "monthly_events": db.scalar(
            select(func.count())
            .select_from(MonthlySalesPlanEvent)
            .where(MonthlySalesPlanEvent.product_id == product_id)
        )
        or 0,
        "purchases": db.scalar(
            select(func.count())
            .select_from(PurchasePlanItem)
            .where(
                or_(
                    PurchasePlanItem.sales_product_id == product_id,
                    PurchasePlanItem.product_id == product_id,
                )
            )
        )
        or 0,
        "batches": db.scalar(
            select(func.count()).select_from(BatchItem).where(BatchItem.product_id == product_id)
        )
        or 0,
        "facts": db.scalar(
            select(func.count()).select_from(SalesFact).where(SalesFact.product_id == product_id)
        )
        or 0,
        "aliases": db.scalar(
            select(func.count())
            .select_from(ProductAlias)
            .where(ProductAlias.product_id == product_id)
        )
        or 0,
        "reasons": db.scalar(
            select(func.count())
            .select_from(DeviationReason)
            .where(DeviationReason.product_id == product_id)
        )
        or 0,
    }


def _strip_draft_rows(db: Session, product_id: uuid.UUID) -> None:
    """Убрать позицию из состава черновиков: без количеств это не движение."""
    plans = db.execute(select(SalesPlan).where(SalesPlan.draft_rows.isnot(None))).scalars().all()
    for plan in plans:
        rows = plan.draft_rows or []
        kept = [row for row in rows if _uuid(row.get("product_id")) != product_id]
        if len(kept) != len(rows):
            plan.draft_rows = kept


def delete_future_product(db: Session, product_id: uuid.UUID) -> None:
    """Удалить неиспользованную позицию; использованную можно только привязать."""
    product = _require_future(db, product_id)
    references = _references(db, product_id)
    used = {key: count for key, count in references.items() if count}
    if used:
        raise DirectoryError(
            "Позиция уже использована в планах или документах — удалить нельзя. "
            "Привяжите её к реальной номенклатуре.",
            status_code=409,
        )
    _strip_draft_rows(db, product_id)
    db.delete(product)
    db.commit()


def _open_correction_blocks(db: Session, product_id: uuid.UUID) -> bool:
    return bool(
        db.scalar(
            select(func.count())
            .select_from(SalesPlanCorrectionItem)
            .join(
                SalesPlanCorrection,
                SalesPlanCorrection.id == SalesPlanCorrectionItem.correction_id,
            )
            .where(
                SalesPlanCorrectionItem.product_id == product_id,
                SalesPlanCorrection.status.in_(OPEN_CORRECTION_STATUSES),
            )
        )
    )


def _merge_plan_items(db: Session, source: Product, target: Product) -> tuple[int, set[uuid.UUID]]:
    """Перенести строки плана; совпадение «клиент + месяц» складывается."""
    rows = (
        db.execute(select(SalesPlanItem).where(SalesPlanItem.product_id == source.id))
        .scalars()
        .all()
    )
    plan_ids: set[uuid.UUID] = set()
    for row in rows:
        plan_ids.add(row.plan_id)
        existing = (
            db.execute(
                select(SalesPlanItem).where(
                    SalesPlanItem.plan_id == row.plan_id,
                    SalesPlanItem.client_id == row.client_id,
                    SalesPlanItem.product_id == target.id,
                    SalesPlanItem.month == row.month,
                )
            )
            .scalars()
            .one_or_none()
        )
        if existing is not None and existing.id != row.id:
            existing.quantity = existing.quantity + row.quantity
            db.delete(row)
        else:
            row.product_id = target.id
    return len(rows), plan_ids


def _merge_correction_items(db: Session, source: Product, target: Product) -> int:
    rows = (
        db.execute(
            select(SalesPlanCorrectionItem).where(SalesPlanCorrectionItem.product_id == source.id)
        )
        .scalars()
        .all()
    )
    for row in rows:
        existing = (
            db.execute(
                select(SalesPlanCorrectionItem).where(
                    SalesPlanCorrectionItem.correction_id == row.correction_id,
                    SalesPlanCorrectionItem.client_id == row.client_id,
                    SalesPlanCorrectionItem.product_id == target.id,
                    SalesPlanCorrectionItem.month == row.month,
                )
            )
            .scalars()
            .one_or_none()
        )
        if existing is not None and existing.id != row.id:
            existing.quantity = existing.quantity + row.quantity
            existing.current_quantity = (existing.current_quantity or Decimal("0")) + (
                row.current_quantity or Decimal("0")
            )
            if existing.notes is None:
                existing.notes = row.notes
            db.delete(row)
        else:
            row.product_id = target.id
    return len(rows)


def _merge_monthly_items(db: Session, source: Product, target: Product) -> int:
    rows = (
        db.execute(select(MonthlySalesPlanItem).where(MonthlySalesPlanItem.product_id == source.id))
        .scalars()
        .all()
    )
    for row in rows:
        existing = (
            db.execute(
                select(MonthlySalesPlanItem).where(
                    MonthlySalesPlanItem.plan_id == row.plan_id,
                    MonthlySalesPlanItem.client_id == row.client_id,
                    MonthlySalesPlanItem.product_id == target.id,
                )
            )
            .scalars()
            .one_or_none()
        )
        if existing is not None and existing.id != row.id:
            existing.annual_quantity = existing.annual_quantity + row.annual_quantity
            existing.quantity = existing.quantity + row.quantity
            if existing.reason is None:
                existing.reason = row.reason
            db.delete(row)
        else:
            row.product_id = target.id
    db.execute(
        update(MonthlySalesPlanEvent)
        .where(MonthlySalesPlanEvent.product_id == source.id)
        .values(product_id=target.id)
    )
    return len(rows)


def bind_future_product(
    db: Session, product_id: uuid.UUID, target_id: uuid.UUID
) -> FutureProductBindOut:
    """Заменить будущую позицию реальной во всех планах и документах."""
    source = _require_future(db, product_id)
    target = db.get(Product, target_id)
    if target is None:
        raise DirectoryError("Позиция номенклатуры не найдена", status_code=404)
    if target.is_future:
        raise DirectoryError("Привязать можно только к реальной позиции из 1С")
    if not target.is_active:
        raise DirectoryError(f"Позиция «{target.code} · {target.name}» отключена")
    if source.id == target.id:
        raise DirectoryError("Это та же самая позиция")
    if _open_correction_blocks(db, source.id):
        raise DirectoryError(
            "Позиция есть в открытой корректировке плана — сначала утвердите или отмените её",
            status_code=409,
        )

    references = _references(db, source.id)
    usage = _plan_usage(db, {source.id})[source.id]
    other_usage = _other_usage(db, {source.id})[source.id]
    draft_plans = set(usage["plan_ids"])

    try:
        plan_rows, plan_ids = _merge_plan_items(db, source, target)
        plan_ids |= draft_plans
        correction_rows = _merge_correction_items(db, source, target)
        monthly_rows = _merge_monthly_items(db, source, target)

        db.execute(
            update(PurchasePlanItem)
            .where(PurchasePlanItem.sales_product_id == source.id)
            .values(sales_product_id=target.id)
        )
        db.execute(
            update(PurchasePlanItem)
            .where(PurchasePlanItem.product_id == source.id)
            .values(product_id=target.id)
        )
        db.execute(
            update(BatchItem).where(BatchItem.product_id == source.id).values(product_id=target.id)
        )
        db.execute(
            update(SalesFact).where(SalesFact.product_id == source.id).values(product_id=target.id)
        )
        db.execute(
            update(ProductAlias)
            .where(ProductAlias.product_id == source.id)
            .values(product_id=target.id)
        )
        db.execute(
            update(DeviationReason)
            .where(DeviationReason.product_id == source.id)
            .values(product_id=target.id)
        )
        _strip_draft_rows(db, source.id)
        db.flush()
        db.delete(source)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise DirectoryError(
            "Не удалось привязать: позиция уже используется в этих же данных. "
            "Проверьте планы и повторите.",
            status_code=409,
        ) from exc

    other_rows = (
        correction_rows
        + monthly_rows
        + references["purchases"]
        + references["batches"]
        + references["facts"]
        + references["aliases"]
        + references["reasons"]
        + references["monthly_events"]
    )
    years = sorted(usage["years"] | other_usage["years"])
    return FutureProductBindOut(
        product_id=target.id,
        product_code=target.code,
        product_name=target.name,
        product_unit=target.unit,
        plan_rows=plan_rows,
        plans=len(plan_ids),
        other_rows=other_rows,
        years=years,
    )
