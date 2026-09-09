"""Minimal application service used by completed menu and business-profile tasks."""

from dataclasses import dataclass

from ..models import Business, Favorite, Service, User
from .rules import RuleError, number, text


@dataclass(frozen=True)
class MenuBusiness:
    id: str
    name: str


@dataclass(frozen=True)
class MainMenuData:
    businesses: tuple[MenuBusiness, ...]
    can_create_business: bool


class Catalog:
    MAX_BUSINESSES_PER_OWNER = 2

    def __init__(self, repo, timezone):
        self.repo = repo
        self.timezone = timezone

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
                businesses=tuple(MenuBusiness(item.id, item.name) for item in businesses),
                can_create_business=len(businesses) < self.MAX_BUSINESSES_PER_OWNER,
            )

    async def owner(self, tx, actor, business_id):
        business = await tx.get(Business, business_id)
        if not business or business.owner_id != actor:
            raise RuleError("Этот бизнес недоступен.")
        return business

    async def create_business(self, actor, name, specialist, description, location, address, comment):
        async with self.repo.transaction() as tx:
            if len(await tx.list(Business, owner_id=actor)) >= self.MAX_BUSINESSES_PER_OWNER:
                raise RuleError("Можно создать не более двух бизнесов.")
            if location not in ("at_master", "at_client", "online", "variable"):
                raise RuleError("Выберите формат работы.")
            business = Business(
                owner_id=actor,
                name=text(name, 80),
                specialist=text(specialist, 80),
                description=text(description, 1000),
                location=location,
                address=address[:500],
                comment=comment[:1000],
            )
            await tx.put(business)
            return business

    async def business(self, business_id):
        async with self.repo.transaction() as tx:
            business = await tx.get(Business, business_id)
            if not business:
                raise RuleError("Специалист не найден. Проверьте ссылку или код.")
            return business

    async def services(self, business_id, actor=None):
        async with self.repo.transaction() as tx:
            business = await tx.get(Business, business_id)
            if not business:
                raise RuleError("Бизнес не найден.")
            values = await tx.list(Service, business_id=business_id)
            return [item for item in values if item.active or business.owner_id == actor]

    async def favorites(self, actor):
        async with self.repo.transaction() as tx:
            result = []
            for favorite in await tx.list(Favorite, user_id=actor):
                business = await tx.get(Business, favorite.business_id)
                if business:
                    result.append(business)
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

    async def update_business(self, actor, business_id, field, value):
        async with self.repo.transaction() as tx:
            business = await self.owner(tx, actor, business_id)
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
            setattr(business, field, value)
            await tx.put(business)
            return business

