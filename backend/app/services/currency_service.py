"""Курсы валют ЦБ РФ.

Официальный курс берётся с `cbr.ru` и кэшируется в таблице `currency_rates`
по паре «дата + валюта». Если ЦБ недоступен, курс можно ввести вручную —
себестоимость пересчитается при следующем сохранении.
"""

from __future__ import annotations

import urllib.error
import urllib.request
import xml.etree.ElementTree as ElementTree
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.domain import Batch
from app.models.rates import CurrencyRate

CBR_URL = "https://www.cbr.ru/scripts/XML_daily.asp"
CBR_TIMEOUT_SECONDS = 10
BASE_CURRENCY = "RUB"


class RateError(Exception):
    """Курс получить не удалось; переносится в HTTP-ответ."""

    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _cbr_url(day: date) -> str:
    return f"{CBR_URL}?date_req={day.strftime('%d/%m/%Y')}"


def parse_cbr_xml(payload: bytes) -> dict[str, tuple[int, Decimal]]:
    """Разбор ответа ЦБ: код валюты → (номинал, рублей за единицу)."""
    root = ElementTree.fromstring(payload.decode("windows-1251", errors="replace"))
    rates: dict[str, tuple[int, Decimal]] = {}
    for valute in root.findall("Valute"):
        code = (valute.findtext("CharCode") or "").strip().upper()
        nominal_raw = (valute.findtext("Nominal") or "1").strip()
        value_raw = (valute.findtext("Value") or "").strip().replace(",", ".")
        if not code or not value_raw:
            continue
        try:
            nominal = int(nominal_raw)
            value = Decimal(value_raw)
        except (ValueError, InvalidOperation):
            continue
        if nominal <= 0:
            continue
        rates[code] = (nominal, value / nominal)
    if not rates:
        raise RateError("ЦБ вернул пустой список курсов")
    return rates


def fetch_cbr_rates(day: date) -> dict[str, tuple[int, Decimal]]:
    """Запрос курсов на дату. Сетевые ошибки превращаются в RateError."""
    request = urllib.request.Request(
        _cbr_url(day),
        headers={"User-Agent": "erp_lite/0.1 (+cbr rates)"},
    )
    try:
        with urllib.request.urlopen(request, timeout=CBR_TIMEOUT_SECONDS) as response:
            payload = response.read()
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise RateError(f"ЦБ РФ недоступен: {exc}. Введите курс вручную") from exc
    return parse_cbr_xml(payload)


def _stored(db: Session, code: str, day: date) -> CurrencyRate | None:
    return (
        db.execute(
            select(CurrencyRate).where(CurrencyRate.code == code, CurrencyRate.rate_date == day)
        )
        .scalars()
        .one_or_none()
    )


def _store(db: Session, code: str, day: date, nominal: int, rate: Decimal) -> CurrencyRate:
    row = _stored(db, code, day)
    if row is None:
        row = CurrencyRate(rate_date=day, code=code, nominal=nominal, rate=rate, source="cbr")
        db.add(row)
    else:
        row.nominal = nominal
        row.rate = rate
        row.source = "cbr"
    db.commit()
    db.refresh(row)
    return row


def get_rate_row(
    db: Session, code: str, day: date, *, allow_fetch: bool = True
) -> CurrencyRate | None:
    """Строка курса на дату: из кэша или с сайта ЦБ. None, если получить не удалось."""
    currency = code.strip().upper()
    if currency == BASE_CURRENCY:
        return None
    row = _stored(db, currency, day)
    if row is not None:
        return row
    if not allow_fetch:
        return None
    try:
        rates = fetch_cbr_rates(day)
    except RateError:
        return None
    if currency not in rates:
        return None
    nominal, rate = rates[currency]
    return _store(db, currency, day, nominal, rate)


def get_rate(db: Session, code: str, day: date, *, allow_fetch: bool = True) -> Decimal | None:
    """Курс валюты на дату; RUB — всегда 1. None, если курса нет и получить не удалось."""
    if code.strip().upper() == BASE_CURRENCY:
        return Decimal("1")
    row = get_rate_row(db, code, day, allow_fetch=allow_fetch)
    return row.rate if row is not None else None


def refresh_rates(db: Session, day: date) -> list[CurrencyRate]:
    """Обновить и сохранить все курсы ЦБ на дату."""
    rates = fetch_cbr_rates(day)
    stored = [_store(db, code, day, nominal, rate) for code, (nominal, rate) in rates.items()]
    return sorted(stored, key=lambda row: row.code)


def resolve_rate(
    db: Session, *, currency: str, day: date, provided: Decimal | None, allow_fetch: bool = True
) -> Decimal:
    """Курс для партии: явный, иначе из ЦБ, иначе ошибка."""
    code = (currency or BASE_CURRENCY).strip().upper()
    if provided is not None and provided > 0:
        return provided
    if code == BASE_CURRENCY:
        return Decimal("1")
    rate = get_rate(db, code, day, allow_fetch=allow_fetch)
    if rate is None:
        raise RateError(
            f"Курс {code} на {day.strftime('%d.%m.%Y')} не найден. "
            "Введите курс вручную или обновите курсы ЦБ"
        )
    return rate


def currency_options(db: Session, day: date) -> list[str]:
    """Валюты, по которым есть курс на дату (для подсказки в интерфейсе)."""
    rows = (
        db.execute(select(CurrencyRate.code).where(CurrencyRate.rate_date == day)).scalars().all()
    )
    return sorted({*rows, BASE_CURRENCY})


def batch_rate(db: Session, batch: Batch) -> Decimal:
    """Курс партии для расчёта: сохранённый, иначе из кэша курсов (без сети)."""
    if batch.current_exchange_rate is not None:
        return batch.current_exchange_rate
    rate = get_rate(db, batch.currency, batch.batch_date, allow_fetch=False)
    return rate if rate is not None else Decimal("1")
