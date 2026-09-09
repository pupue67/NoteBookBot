### Правила ввода: проверка текста, чисел, времени, интервалов и дат с понятными ошибками для пользователя.
from datetime import datetime

from ..models import Interval


class RuleError(Exception):
    """Safe, user-facing business rule failure."""


def text(value, maximum=500):
    value = str(value).strip()
    if not value or len(value) > maximum:
        raise RuleError(f"Введите текст от 1 до {maximum} символов.")
    return value


def number(value, minimum=0, maximum=1000000):
    try:
        result = int(str(value).strip())
    except ValueError:
        raise RuleError("Введите целое число.") from None
    if not minimum <= result <= maximum:
        raise RuleError(f"Введите число от {minimum} до {maximum}.")
    return result


def minute(value):
    try:
        h, m = map(int, value.strip().split(":"))
        if h == 24 and m == 0:
            return 1440
        if not (0 <= h < 24 and 0 <= m < 60):
            raise ValueError
        return h * 60 + m
    except ValueError:
        raise RuleError("Введите время в формате ЧЧ:ММ, например 15:30.") from None


def hhmm(value):
    return f"{value // 60:02}:{value % 60:02}"


def intervals(value):
    if value.strip() == "-":
        return []
    result = []
    for part in value.replace("–", "-").replace("—", "-").split(","):
        try:
            start, end = part.strip().split("-")
        except ValueError:
            raise RuleError("Пример: 10:00-13:00, 15:00-20:00. Выходной: -") from None
        item = Interval(start=minute(start), end=minute(end))
        if item.start >= item.end:
            raise RuleError("Начало интервала должно быть раньше конца, в пределах одного дня.")
        result.append(item)
    result.sort(key=lambda x: x.start)
    if any(a.end > b.start for a, b in zip(result, result[1:])):
        raise RuleError("Интервалы не должны пересекаться.")
    return result


def local_date(value):
    try:
        return datetime.strptime(value.strip(), "%d.%m.%Y").date()
    except ValueError:
        raise RuleError("Введите дату ДД.ММ.ГГГГ, например 16.09.2026.") from None
