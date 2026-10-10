"""Курсы валют ЦБ РФ.

Официальный курс берётся с `cbr.ru` и кэшируется в `currency_rates` по дате,
которую сообщает сам ЦБ (в выходные он отдаёт курс прошлого рабочего дня).

Курс живёт в кэше час: незакрытая часть валютного инвойса оценивается по последнему
доступному курсу и потому пересчитывается сама, а курсы уже сделанных платежей
хранятся в платежах и не меняются никогда.
"""

from __future__ import annotations

import urllib.error
import urllib.request
import xml.etree.ElementTree as ElementTree
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.rates import CurrencyRate

CBR_URL = "https://www.cbr.ru/scripts/XML_daily.asp"
CBR_TIMEOUT_SECONDS = 10
BASE_CURRENCY = "RUB"
RATE_TTL = timedelta(hours=1)
FETCH_LOOKBACK_DAYS = 10


class RateError(Exception):
    """Курс получить не удалось; переносится в HTTP-ответ."""

    def __init__(self, message: str, *, status_code: int = 502) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class CbrRates:
    """Ответ ЦБ: дата, к которой относятся курсы, и сами курсы."""

    rate_date: date
    rates: dict[str, tuple[int, Decimal]]


def _cbr_url(day: date) -> str:
    return f"{CBR_URL}?date_req={day.strftime('%d/%m/%Y')}"


def _parse(payload: bytes) -> tuple[date | None, dict[str, tuple[int, Decimal]]]:
    root = ElementTree.fromstring(payload.decode("windows-1251", errors="replace"))
    rate_date: date | None = None
    raw_date = (root.get("Date") or "").strip()
    if raw_date:
        try:
            rate_date = datetime.strptime(raw_date, "%d.%m.%Y").date()
        except ValueError:
            rate_date = None

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
    return rate_date, rates


def parse_cbr_xml(payload: bytes) -> dict[str, tuple[int, Decimal]]:
    """Разбор ответа ЦБ: код валюты → (номинал, рублей за единицу)."""
    return _parse(payload)[1]


def fetch_cbr_rates(day: date) -> CbrRates:
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
    actual_date, rates = _parse(payload)
    return CbrRates(rate_date=actual_date or day, rates=rates)


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
    row.fetched_at = datetime.now(UTC)
    db.commit()
    db.refresh(row)
    return row


def refresh_rates(db: Session, day: date) -> list[CurrencyRate]:
    """Обновить и сохранить все курсы ЦБ на дату (одна выгрузка на дату)."""
    fetched = fetch_cbr_rates(day)
    stored = [
        _store(db, code, fetched.rate_date, nominal, rate)
        for code, (nominal, rate) in fetched.rates.items()
    ]
    return sorted(stored, key=lambda row: row.code)


def get_rate_row(
    db: Session, code: str, day: date, *, allow_fetch: bool = True
) -> CurrencyRate | None:
    """Курс на конкретную дату: из кэша или с сайта ЦБ."""
    currency = code.strip().upper()
    if currency == BASE_CURRENCY:
        return None
    row = _stored(db, currency, day)
    if row is not None:
        return row
    if not allow_fetch:
        return None
    try:
        fetched = fetch_cbr_rates(day)
    except RateError:
        return None
    if currency not in fetched.rates:
        return None
    nominal, rate = fetched.rates[currency]
    return _store(db, currency, fetched.rate_date, nominal, rate)


def latest_rate_row(
    db: Session, code: str, *, allow_fetch: bool = True, ttl: timedelta = RATE_TTL
) -> CurrencyRate | None:
    """Последний доступный курс: из кэша, если ему меньше часа, иначе заново с ЦБ."""
    currency = code.strip().upper()
    if currency == BASE_CURRENCY:
        return None
    row = (
        db.execute(
            select(CurrencyRate)
            .where(CurrencyRate.code == currency, CurrencyRate.rate_date <= date.today())
            .order_by(CurrencyRate.rate_date.desc())
            .limit(1)
        )
        .scalars()
        .one_or_none()
    )
    fresh = row is not None and datetime.now(UTC) - row.fetched_at < ttl
    if fresh or not allow_fetch:
        return row
    # Кэш устарел или пуст: тянем свежий курс (в выходные ЦБ отдаёт прошлый рабочий день).
    for shift in range(FETCH_LOOKBACK_DAYS):
        try:
            fetched = fetch_cbr_rates(date.today() - timedelta(days=shift))
        except RateError:
            return row
        if currency in fetched.rates:
            nominal, rate = fetched.rates[currency]
            return _store(db, currency, fetched.rate_date, nominal, rate)
    return row


def get_rate(db: Session, code: str, day: date, *, allow_fetch: bool = True) -> Decimal | None:
    """Курс валюты на дату; RUB — всегда 1. None, если курса нет."""
    if code.strip().upper() == BASE_CURRENCY:
        return Decimal("1")
    row = get_rate_row(db, code, day, allow_fetch=allow_fetch)
    return row.rate if row is not None else None


def resolve_rate(
    db: Session, *, currency: str, day: date, provided: Decimal | None, allow_fetch: bool = True
) -> Decimal:
    """Курс партии: явный, иначе последний доступный (ЦБ), иначе ошибка."""
    code = (currency or BASE_CURRENCY).strip().upper()
    if provided is not None and provided > 0:
        return provided
    if code == BASE_CURRENCY:
        return Decimal("1")
    row = latest_rate_row(db, code, allow_fetch=allow_fetch)
    if row is None:
        raise RateError(f"Курс {code} не найден. Введите курс вручную или обновите курсы ЦБ")
    return row.rate


def batch_rate(db: Session, currency: str, fallback: Decimal | None) -> tuple[Decimal, object]:
    """Курс для незакрытой части партии и строка курса (нужна дата обновления)."""
    code = (currency or BASE_CURRENCY).strip().upper()
    if code == BASE_CURRENCY:
        return Decimal("1"), None
    row = latest_rate_row(db, code)
    if row is not None:
        return row.rate, row
    return (fallback if fallback is not None else Decimal("1")), None


def refresh_used_rates(db: Session) -> int:
    """Часовое обновление: освежить курсы валют, которые есть в поступлениях."""
    from app.models.domain import Batch

    currencies = {
        code.upper()
        for (code,) in db.execute(select(Batch.currency).distinct()).all()
        if code and code.upper() != BASE_CURRENCY
    }
    refreshed = 0
    for currency in currencies:
        if latest_rate_row(db, currency) is not None:
            refreshed += 1
    return refreshed
