"""Логика работы с бизнесами, услугами, расписанием, клиентами и доступным временем для записи."""
from dataclasses import dataclass
from datetime import datetime, timedelta

from ..models import (
    Appointment,
    Business,
    Client,
    DateOverride,
    DayRule,
    Favorite,
    Notification,
    Service,
    TimeNote,
    User,
)
from .availability import available_times, effective_day, occupies
from .rules import RuleError, number, text


@dataclass(frozen=True)
class MenuBusiness:
    id: str
    name: str


MAX_BUSINESSES_PER_OWNER = 2


@dataclass(frozen=True)
class MainMenuData:
    businesses: tuple[MenuBusiness, ...]
    can_create_business: bool


class Catalog:
    def __init__(self, repo, timezone, clock=None):
        self.repo = repo
        self.timezone = timezone
        self.clock = clock or (lambda: datetime.now(timezone))

    async def user(self, telegram_id, name):
        async with self.repo.transaction() as tx:
            users = await tx.list(User, telegram_id=telegram_id)
            user = users[0] if users else User(telegram_id=telegram_id, name=name)
            user.name = name
            await tx.put(user)
            return user

    async def get_main_menu_data(self, telegram_user_id):
        async with self.repo.transaction() as tx:
            users = await tx.list(User, telegram_id=telegram_user_id)
            businesses = await tx.list(Business, owner_id=users[0].id) if users else []
            return MainMenuData(
                tuple(MenuBusiness(b.id, b.name) for b in businesses),
                len(businesses) < MAX_BUSINESSES_PER_OWNER,
            )

    async def owner(self, tx, actor, business_id):
        b = await tx.get(Business, business_id)
        if not b or b.owner_id != actor:
            raise RuleError("Этот бизнес недоступен.")
        return b

    async def create_business(self, actor, name, specialist, description, location, address, comment):
        async with self.repo.transaction() as tx:
            if len(await tx.list(Business, owner_id=actor)) >= MAX_BUSINESSES_PER_OWNER:
                raise RuleError("Можно создать не более двух бизнесов.")
            if location not in ("at_master", "at_client", "online", "variable"):
                raise RuleError("Выберите формат работы кнопкой.")
            b = Business(
                owner_id=actor,
                name=text(name, 80),
                specialist=text(specialist, 80),
                description=text(description, 1000),
                location=location,
                address=address[:500],
                comment=comment[:1000],
            )
            await tx.put(b)
            return b

    async def business(self, id):
        async with self.repo.transaction() as tx:
            b = await tx.get(Business, id)
            if not b:
                raise RuleError("Специалист не найден. Проверьте ссылку или код.")
            return b

    async def update_business(self, actor, id, field, value):
        async with self.repo.transaction() as tx:
            b = await self.owner(tx, actor, id)
            if field in ("name", "specialist"):
                value = text(value, 80)
            elif field in ("description", "address", "comment", "payment_details"):
                value = "" if value == "-" else text(value, 1000)
            elif field in ("buffer_min", "notice_min", "cancel_notice_min", "move_notice_min"):
                value = number(value, 0, 43200)
            elif field == "horizon_days":
                value = number(value, 1, 180)
            elif field == "increment_min":
                value = number(value, 1, 60)
            elif field == "accepts_new":
                value = bool(value)
            else:
                raise RuleError("Настройка недоступна.")
            setattr(b, field, value)
            await tx.put(b)
            return b

    async def set_booking_until(self, actor, business_id, last_day):
        today = self.clock().date()
        async with self.repo.transaction() as tx:
            business = await self.owner(tx, actor, business_id)
            if last_day is not None and not today <= last_day <= today + timedelta(days=180):
                raise RuleError("Выберите дату от сегодня до 180 дней вперёд.")
            if last_day is not None:
                if business.booking_until is None:
                    business.horizon_before_calendar = business.horizon_days
                business.horizon_days = max(1, (last_day - today).days)
            else:
                business.horizon_days = business.horizon_before_calendar or 30
                business.horizon_before_calendar = None
            business.booking_until = last_day
            await tx.put(business)
            return business

    async def services(self, business_id, actor=None):
        async with self.repo.transaction() as tx:
            b = await tx.get(Business, business_id)
            if not b:
                raise RuleError("Бизнес не найден.")
            return [
                s for s in await tx.list(Service, business_id=business_id) if s.active or b.owner_id == actor
            ]

    async def service(self, id):
        async with self.repo.transaction() as tx:
            s = await tx.get(Service, id)
            if not s:
                raise RuleError("Услуга не найдена.")
            return s

    async def save_service(self, actor, business_id, name, price, mode, duration, prepay=0, id=None):
        async with self.repo.transaction() as tx:
            b = await self.owner(tx, actor, business_id)
            if mode not in ("fixed", "personal"):
                raise RuleError("Выберите режим длительности.")
            s = await tx.get(Service, id) if id else Service(business_id=business_id, name=name)
            if not s or s.business_id != business_id:
                raise RuleError("Услуга недоступна.")
            s.name, s.price_rub = text(name, 100), number(price)
            s.mode, s.duration_min = mode, number(duration, 1, 1440)
            s.prepay_rub = number(prepay, 0, s.price_rub)
            if s.prepay_rub and not b.payment_details:
                raise RuleError("Сначала укажите реквизиты в настройках бизнеса.")
            await tx.put(s)
            return s

    async def toggle_service(self, actor, id):
        async with self.repo.transaction() as tx:
            s = await tx.get(Service, id)
            if not s:
                raise RuleError("Услуга не найдена.")
            await self.owner(tx, actor, s.business_id)
            s.active = not s.active
            await tx.put(s)

    async def schedule(self, actor, business_id, day=None):
        async with self.repo.transaction() as tx:
            b = await self.owner(tx, actor, business_id)
            if day:
                return await effective_day(tx, b, day)
            return await tx.list(DayRule, business_id=business_id)

    async def edit_schedule(self, actor, business_id, key, field, value):
        async with self.repo.transaction() as tx:
            b = await self.owner(tx, actor, business_id)
            is_week = isinstance(key, int)
            if is_week:
                found = await tx.list(DayRule, business_id=business_id, weekday=key)
                rule = found[0] if found else DayRule(business_id=business_id, weekday=key)
            else:
                found = await tx.list(DateOverride, business_id=business_id, day=key)
                rule = found[0] if found else DateOverride(business_id=business_id, day=key)
            if field == "limit":
                rule.limit = None if value == "-" else number(value, 0, 1000)
                if not is_week:
                    rule.limit_override = True
            elif field == "intervals":
                rule.intervals = value
                if not is_week:
                    rule.day_off = False
            elif field == "comment":
                rule.comment = "" if value == "-" else text(value, 1000)
            elif field == "closed" and not is_week:
                rule.closed.extend(value)
            elif field == "clear_closed" and not is_week:
                rule.closed = []
            elif field == "day_off" and not is_week:
                rule.day_off = True
            elif field == "address" and not is_week:
                rule.address = "" if value == "-" else text(value, 500)
            elif field == "reset" and not is_week:
                await tx.delete(DateOverride, rule.id)
                return []
            else:
                raise RuleError("Изменение недоступно.")
            await tx.put(rule)
            # Existing appointments remain unchanged. Report conflicts rather than cancelling them.
            conflicts = []
            for a in await tx.list(Appointment, business_id=business_id):
                if not occupies(a, self.clock()) or a.start < self.clock():
                    continue
                if (a.start.weekday() != key) if is_week else (a.start.date() != key):
                    continue
                work, closed, limit, _, _ = await effective_day(tx, b, a.start.date())
                minute = a.start.hour * 60 + a.start.minute
                count = sum(
                    1
                    for x in await tx.list(Appointment, business_id=business_id)
                    if x.start.date() == a.start.date() and occupies(x, self.clock())
                )
                if (
                    not any(w.start <= minute and minute + a.duration_min <= w.end for w in work)
                    or any(minute < c.end and minute + a.duration_min > c.start for c in closed)
                    or (limit is not None and count > limit)
                ):
                    conflicts.append(a)
            return conflicts

    async def set_time_note(self, actor, business_id, day, minute, comment, address):
        async with self.repo.transaction() as tx:
            await self.owner(tx, actor, business_id)
            items = await tx.list(TimeNote, business_id=business_id, day=day, minute=minute)
            note = items[0] if items else TimeNote(business_id=business_id, day=day, minute=minute)
            note.comment, note.address = comment[:1000], address[:500]
            await tx.put(note)

    async def client(self, tx, business_id, user_id=None, name=None):
        if user_id:
            items = await tx.list(Client, business_id=business_id, user_id=user_id)
            if items:
                return items[0]
            u = await tx.get(User, user_id)
            if not u:
                raise RuleError("Клиент не найден.")
            name = u.name
        c = Client(business_id=business_id, user_id=user_id, name=text(name, 100))
        await tx.put(c)
        return c

    async def clients(self, actor, business_id):
        async with self.repo.transaction() as tx:
            await self.owner(tx, actor, business_id)
            return await tx.list(Client, business_id=business_id)

    async def favorites(self, actor):
        async with self.repo.transaction() as tx:
            result = []
            for f in await tx.list(Favorite, user_id=actor):
                b = await tx.get(Business, f.business_id)
                if b:
                    result.append(b)
            return result

    async def favorite(self, actor, business_id):
        async with self.repo.transaction() as tx:
            if not await tx.get(Business, business_id):
                raise RuleError("Специалист не найден.")
            values = await tx.list(Favorite, user_id=actor, business_id=business_id)
            if values:
                await tx.delete(Favorite, values[0].id)
            else:
                await tx.put(Favorite(user_id=actor, business_id=business_id))

    async def dates(self, actor, service_id, start_day=None, appointment_id=None):
        async with self.repo.transaction() as tx:
            s = await tx.get(Service, service_id)
            if not s:
                raise RuleError("Услуга не найдена.")
            b = await tx.get(Business, s.business_id)
            clients = await tx.list(Client, business_id=b.id, user_id=actor)
            client_id = clients[0].id if clients else None
            duration = None
            if appointment_id:
                a = await tx.get(Appointment, appointment_id)
                c = await tx.get(Client, a.client_id) if a else None
                if not a or not c or a.service_id != s.id or actor not in (b.owner_id, c.user_id):
                    raise RuleError("Запись недоступна.")
                client_id, duration = a.client_id, a.required_duration or a.duration_min
            first = max(start_day or self.clock().date(), self.clock().date())
            last = self.clock().date() + timedelta(days=b.horizon_days)
            if b.booking_until is not None:
                last = min(last, b.booking_until)
            result = []
            for offset in range((last - first).days + 1):
                day = first + timedelta(days=offset)
                if await available_times(
                    tx,
                    b,
                    s,
                    client_id,
                    day,
                    self.clock(),
                    exclude=appointment_id,
                    duration=duration,
                    existing=bool(appointment_id),
                ):
                    result.append(day)
            return result

    async def times(self, actor, service_id, day, appointment_id=None):
        async with self.repo.transaction() as tx:
            s = await tx.get(Service, service_id)
            if not s:
                raise RuleError("Услуга не найдена.")
            b = await tx.get(Business, s.business_id)
            clients = await tx.list(Client, business_id=b.id, user_id=actor)
            client_id, duration = (clients[0].id if clients else None), None
            if appointment_id:
                a = await tx.get(Appointment, appointment_id)
                c = await tx.get(Client, a.client_id) if a else None
                if not a or not c or a.service_id != s.id or actor not in (b.owner_id, c.user_id):
                    raise RuleError("Запись недоступна.")
                client_id, duration = a.client_id, a.required_duration or a.duration_min
            return await available_times(
                tx,
                b,
                s,
                client_id,
                day,
                self.clock(),
                exclude=appointment_id,
                duration=duration,
                existing=bool(appointment_id),
            )

    async def notify(self, tx, appointment, message):
        b = await tx.get(Business, appointment.business_id)
        c = await tx.get(Client, appointment.client_id)
        for user_id in set([b.owner_id, c.user_id]) - {None}:
            await tx.put(Notification(user_id=user_id, text=message, appointment_id=appointment.id))
