"""Заморозка прошедших месяцев планов.

Правило (согласовано): год меньше текущего — заморожен целиком; текущий год —
месяцы строго до текущего; будущий год — редактируется весь. Проверка идёт по
серверной дате и ничего не хранит.
"""

from __future__ import annotations

from datetime import date

MONTHS = tuple(range(1, 13))


def frozen_months(year: int, *, today: date | None = None) -> set[int]:
    """Месяцы плана, которые нельзя менять."""
    current = today or date.today()
    if year < current.year:
        return set(MONTHS)
    if year > current.year:
        return set()
    return set(range(1, current.month))


def editable_months(year: int, *, today: date | None = None) -> list[int]:
    """Месяцы, доступные для правки."""
    frozen = frozen_months(year, today=today)
    return [month for month in MONTHS if month not in frozen]


def check_months_editable(year: int, months: set[int], *, today: date | None = None) -> None:
    """Бросает ValueError, если среди месяцев есть замороженные."""
    frozen = frozen_months(year, today=today)
    blocked = sorted(month for month in months if month in frozen)
    if blocked:
        raise ValueError(
            "Замороженные месяцы менять нельзя: "
            + ", ".join(str(month) for month in blocked)
            + f" (год {year}, правило — прошедшие периоды)"
        )
