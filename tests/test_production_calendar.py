from datetime import date

import production_calendar as pc


def test_known_month_totals_2026():
    # Производственный календарь РФ на 2026 год
    assert pc.working_days_in_month(2026, 1) == 15   # новогодние каникулы 1–9 января
    assert pc.working_days_in_month(2026, 2) == 19   # 23 февраля
    assert pc.working_days_in_month(2026, 3) == 21   # перенос 8 марта → 9 марта
    assert pc.working_days_in_month(2026, 5) == 19   # 1 мая + перенос 9 мая → 11 мая
    assert pc.working_days_in_month(2026, 6) == 21   # 12 июня
    assert pc.working_days_in_month(2026, 7) == 23   # праздников нет
    assert pc.working_days_in_month(2026, 11) == 20  # 4 ноября
    assert pc.working_days_in_month(2026, 12) == 22  # перенос → 31 декабря выходной


def test_is_working_day_2026():
    assert pc.is_working_day(date(2026, 1, 8)) is False    # каникулы (четверг)
    assert pc.is_working_day(date(2026, 1, 9)) is False    # перенос (пятница)
    assert pc.is_working_day(date(2026, 1, 12)) is True    # первый рабочий понедельник
    assert pc.is_working_day(date(2026, 3, 9)) is False    # перенос 8 марта
    assert pc.is_working_day(date(2026, 5, 11)) is False   # перенос 9 мая
    assert pc.is_working_day(date(2026, 12, 31)) is False  # перенос
    assert pc.is_working_day(date(2026, 7, 4)) is False    # обычная суббота
    assert pc.is_working_day(date(2026, 7, 6)) is True     # обычный понедельник


def test_up_to_day_counts_inclusive():
    # К 9 января 2026 ни одного рабочего дня, к 12 января — один
    assert pc.working_days_in_month(2026, 1, up_to_day=9) == 0
    assert pc.working_days_in_month(2026, 1, up_to_day=12) == 1


def test_fallback_year_uses_fixed_holidays():
    # 2030 года нет в данных: будни минус фиксированные праздники, без переносов
    assert pc.is_working_day(date(2030, 1, 3)) is False    # каникулы (четверг)
    assert pc.is_working_day(date(2030, 5, 1)) is False    # 1 мая (среда)
    # 23 февраля 2030 — суббота: и так выходной, переноса в fallback нет
    assert pc.is_working_day(date(2030, 2, 25)) is True    # понедельник — рабочий
