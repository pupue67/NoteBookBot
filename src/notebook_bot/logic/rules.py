"""Shared validation rules required by Telegram forms."""

from datetime import date

from ..models import Interval


class RuleError(Exception):
    pass


def text(value, limit=1000):
    value = str(value).strip()
    if not value:
        raise RuleError("Значение не может быть пустым.")
    if len(value) > limit:
        raise RuleError(f"Допустимо не более {limit} символов.")
    return value


def number(value, minimum=0, maximum=1_000_000):
    try:
        result = int(value)
    except (TypeError, ValueError):
        raise RuleError("Введите целое число.") from None
    if not minimum <= result <= maximum:
        raise RuleError(f"Введите число от {minimum} до {maximum}.")
    return result


def minute(value):
    try:
        hour, minute_value = map(int, str(value).strip().split(":"))
    except (TypeError, ValueError):
        raise RuleError("Введите время в формате ЧЧ:ММ.") from None
    result = hour * 60 + minute_value
    if hour not in range(25) or minute_value not in range(60) or result > 1440:
        raise RuleError("Введите корректное время.")
    return result


def intervals(value):
    result = []
    for part in str(value).replace(";", ",").split(","):
        try:
            start, end = part.strip().split("-")
        except ValueError:
            raise RuleError("Введите интервалы, например: 10:00-13:00, 15:00-20:00.") from None
        item = Interval(start=minute(start), end=minute(end))
        if item.start >= item.end:
            raise RuleError("Начало интервала должно быть раньше окончания.")
        result.append(item)
    ordered = sorted(result, key=lambda item: item.start)
    if any(left.end > right.start for left, right in zip(ordered, ordered[1:])):
        raise RuleError("Рабочие интервалы не должны пересекаться.")
    return ordered


def local_date(value):
    try:
        return date.fromisoformat(str(value).strip())
    except ValueError:
        raise RuleError("Введите дату в формате ГГГГ-ММ-ДД.") from None

