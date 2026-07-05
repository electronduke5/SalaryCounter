"""Производственный календарь РФ.

HOLIDAYS — нерабочие будни (праздники + перенесённые выходные) по годам,
по постановлениям Правительства РФ. WORKING_WEEKENDS — рабочие субботы/воскресенья
(при переносах; в 2026 их нет).

Для года, которого нет в HOLIDAYS, действует fallback: будни минус фиксированные
федеральные праздники (без переносов) — обновите данные, когда выйдет постановление
на новый год.
"""

from calendar import monthrange
from datetime import date
from typing import Dict, Optional, Set, Tuple

# Фиксированные праздники ТК РФ (месяц, день) — fallback для лет без данных
_BASE_HOLIDAYS = {
    (1, 1), (1, 2), (1, 3), (1, 4), (1, 5), (1, 6), (1, 7), (1, 8),
    (2, 23), (3, 8), (5, 1), (5, 9), (6, 12), (11, 4),
}

HOLIDAYS: Dict[int, Set[Tuple[int, int]]] = {
    # Постановление Правительства РФ о переносе выходных дней в 2026 году:
    # 3 янв (сб) → 9 янв (пт), 4 янв (вс) → 31 дек (чт),
    # 8 марта (вс) → 9 марта (пн), 9 мая (сб) → 11 мая (пн).
    2026: {
        (1, 1), (1, 2), (1, 5), (1, 6), (1, 7), (1, 8), (1, 9),
        (2, 23),
        (3, 9),
        (5, 1), (5, 11),
        (6, 12),
        (11, 4),
        (12, 31),
    },
}

WORKING_WEEKENDS: Dict[int, Set[Tuple[int, int]]] = {
    2026: set(),
}


def is_working_day(d: date) -> bool:
    md = (d.month, d.day)
    if d.year in HOLIDAYS:
        if d.weekday() >= 5:
            return md in WORKING_WEEKENDS.get(d.year, set())
        return md not in HOLIDAYS[d.year]
    # Fallback: будни минус фиксированные праздники, переносы неизвестны
    return d.weekday() < 5 and md not in _BASE_HOLIDAYS


def working_days_in_month(year: int, month: int, up_to_day: Optional[int] = None) -> int:
    """Число рабочих дней в месяце; up_to_day — включительно до этого числа."""
    last = monthrange(year, month)[1]
    if up_to_day is not None:
        last = min(last, up_to_day)
    return sum(1 for day in range(1, last + 1) if is_working_day(date(year, month, day)))
