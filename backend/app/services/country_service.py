"""Справочник стран: заведение и правка. Читать может любой вошедший.

Срок доставки задаётся в днях и используется планом закупок, чтобы сдвинуть
месяц заказа назад от месяца потребности.
"""

from __future__ import annotations

import uuid

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.counterparties import name_key
from app.models.countries import Country
from app.schemas.countries import CountryIn, CountryUpdate
from app.services.directory_service import DirectoryError


def _normalize(name: str) -> str:
    return " ".join(name.split()).strip()


def list_countries(db: Session, *, include_inactive: bool = False) -> list[Country]:
    statement = select(Country).order_by(Country.name)
    if not include_inactive:
        statement = statement.where(Country.is_active.is_(True))
    return list(db.execute(statement).scalars().all())


def get_country(db: Session, country_id: uuid.UUID) -> Country:
    country = db.get(Country, country_id)
    if country is None:
        raise DirectoryError("Страна не найдена", status_code=404)
    return country


def create_country(db: Session, payload: CountryIn) -> Country:
    name = _normalize(payload.name)
    if not name:
        raise DirectoryError("Укажите название страны")
    key = name_key(name)
    exists = db.execute(select(Country).where(Country.name_key == key)).scalars().one_or_none()
    if exists is not None:
        raise DirectoryError(f"Страна «{name}» уже есть в справочнике", status_code=409)
    country = Country(
        name=name,
        name_key=key,
        delivery_days=payload.delivery_days,
        is_active=payload.is_active,
        source="manual",
    )
    db.add(country)
    try:
        db.commit()
    except IntegrityError as exc:  # гонка двух одновременных созданий
        db.rollback()
        raise DirectoryError(f"Страна «{name}» уже есть в справочнике", status_code=409) from exc
    db.refresh(country)
    return country


def update_country(db: Session, country_id: uuid.UUID, payload: CountryUpdate) -> Country:
    country = get_country(db, country_id)
    data = payload.model_dump(exclude_unset=True)
    if data.get("name") is not None:
        name = _normalize(str(data["name"]))
        if not name:
            raise DirectoryError("Название страны не может быть пустым")
        key = name_key(name)
        twin = db.execute(select(Country).where(Country.name_key == key)).scalars().one_or_none()
        if twin is not None and twin.id != country.id:
            raise DirectoryError(f"Страна «{name}» уже есть в справочнике", status_code=409)
        data["name"] = name
        data["name_key"] = key
    for field, value in data.items():
        setattr(country, field, value)
    db.commit()
    db.refresh(country)
    return country
