import asyncio

import pytest

from notebook_bot.bot.menu import build_keyboard
from notebook_bot.logic.rules import RuleError, intervals
from notebook_bot.models import Business
from conftest import stamp


async def second_business(app, owner):
    return await app.create_business(owner.id, "Второй кабинет", "Анна", "Описание", "online", "", "")


def callbacks(data):
    return [b.callback_data for row in build_keyboard(data).inline_keyboard for b in row]


async def test_menu_zero_one_two_and_creation_limit(setup_app):
    app, master, _, other, first, _, _ = setup_app
    empty = await app.get_main_menu_data(other.telegram_id)
    assert empty.businesses == () and empty.can_create_business
    assert "nav:create" in callbacks(empty)
    assert (await app.get_main_menu_data(999999)).businesses == ()
    one = await app.get_main_menu_data(master.telegram_id)
    assert [(b.id, b.name) for b in one.businesses] == [(first.id, first.name)]
    assert "nav:create" in callbacks(one)
    second = await second_business(app, master)
    two = await app.get_main_menu_data(master.telegram_id)
    assert not two.can_create_business
    assert set(callbacks(two)) == {
        "nav:appointments", "nav:specialists", f"nav:business:{first.id}", f"nav:business:{second.id}"
    }
    with pytest.raises(RuleError, match="двух"):
        await second_business(app, master)
    # The limit is per owner, not global.
    await second_business(app, other)


async def test_concurrent_creation_cannot_make_third_business(setup_app):
    app, master, *_ = setup_app
    results = await asyncio.gather(
        second_business(app, master), second_business(app, master), return_exceptions=True
    )
    assert sum(isinstance(r, Business) for r in results) == 1
    assert sum(isinstance(r, RuleError) for r in results) == 1
    assert len((await app.get_main_menu_data(master.telegram_id)).businesses) == 2


async def test_services_calendars_bookings_and_clients_are_independent(setup_app):
    app, master, client, other, first, service1, _ = setup_app
    second = await second_business(app, master)
    service2 = await app.save_service(master.id, second.id, "Консультация", 900, "fixed", 60)
    day = stamp(app).date()
    assert not await app.times(client.id, service2.id, day)
    await app.edit_schedule(master.id, second.id, day.weekday(), "intervals", intervals("10:00-12:00"))
    await app.edit_schedule(master.id, first.id, day, "limit", 1)
    a1 = await app.create(client.id, service1.id, stamp(app))
    assert day not in await app.dates(other.id, service1.id)
    assert stamp(app) in await app.times(client.id, service2.id, day)
    a2 = await app.create(client.id, service2.id, stamp(app))
    assert a1.client_id != a2.client_id
    assert (a1.duration_min, a1.price_rub) == (40, 2000)
    assert (a2.duration_min, a2.price_rub) == (60, 900)
    assert [s.id for s in await app.services(first.id)] == [service1.id]
    assert [s.id for s in await app.services(second.id)] == [service2.id]
    assert [a.id for a in await app.appointments(master.id, first.id)] == [a1.id]
    assert [a.id for a in await app.appointments(master.id, second.id)] == [a2.id]
    assert {a.id for a in await app.appointments(client.id)} == {a1.id, a2.id}
    conflicts = await app.edit_schedule(master.id, first.id, day, "day_off", None)
    assert [a.id for a in conflicts] == [a1.id]
    assert stamp(app, hour=11) in await app.times(other.id, service2.id, day)
    await app.cancel(master.id, a1.id, a1.revision)
    assert (await app.get_appointment(client.id, a2.id))[0].status == "booked"
    with pytest.raises(RuleError):
        await app.save_service(master.id, second.id, "Чужая услуга", 1, "fixed", 20, id=service1.id)
    with pytest.raises(RuleError):
        await app.create(master.id, service2.id, stamp(app, hour=11), client_id=a1.client_id)


async def test_personal_duration_does_not_leak_to_second_business(setup_app):
    app, master, client, _, first, service1, _ = setup_app
    second = await second_business(app, master)
    await app.save_service(master.id, first.id, service1.name, 2000, "personal", 60, id=service1.id)
    service2 = await app.save_service(master.id, second.id, service1.name, 900, "personal", 60)
    await app.edit_schedule(master.id, second.id, stamp(app).weekday(), "intervals", intervals("10:00-13:00"))
    a1 = await app.create(client.id, service1.id, stamp(app))
    await app.set_duration(master.id, a1.id, 35)
    a2 = await app.create(client.id, service2.id, stamp(app))
    assert a2.status == "awaiting_duration"
    await app.set_duration(master.id, a2.id, 55)
    again1 = await app.create(client.id, service1.id, stamp(app, hour=11))
    again2 = await app.create(client.id, service2.id, stamp(app, hour=11))
    assert again1.duration_min == 35
    assert again2.duration_min == 55
