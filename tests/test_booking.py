import asyncio
from datetime import date, timedelta

import pytest

from notebook_bot.logic.rules import RuleError, intervals
from notebook_bot.models import Appointment, Client, Notification
from conftest import stamp


async def test_concurrent_creation_only_one_wins(setup_app):
    app, m, c, other, b, s, _ = setup_app
    results = await asyncio.gather(
        app.create(c.id, s.id, stamp(app)), app.create(other.id, s.id, stamp(app)), return_exceptions=True
    )
    assert sum(isinstance(x, Appointment) for x in results) == 1
    assert sum(isinstance(x, RuleError) for x in results) == 1


async def test_repeat_callback_no_duplicate(setup_app):
    app, m, c, _, b, s, _ = setup_app
    first = await app.create(c.id, s.id, stamp(app))
    second = await app.create(c.id, s.id, stamp(app))
    assert first.id == second.id
    assert len(await app.appointments(c.id)) == 1


async def test_personal_duration_is_saved_and_price_unchanged(setup_app):
    app, m, c, _, b, s, _ = setup_app
    await app.save_service(m.id, b.id, s.name, 2000, "personal", 60, id=s.id)
    a = await app.create(c.id, s.id, stamp(app))
    assert a.status == "awaiting_duration"
    a, fits = await app.set_duration(m.id, a.id, 35)
    assert fits and a.duration_min == 35 and a.status == "booked"
    a2 = await app.create(c.id, s.id, stamp(app, day=9))
    assert a2.duration_min == 35 and a2.price_rub == 2000 and a2.status == "booked"


async def test_duration_does_not_fit_keeps_original(setup_app):
    app, m, c, other, b, s, _ = setup_app
    a = await app.create(c.id, s.id, stamp(app))
    await app.create(other.id, s.id, stamp(app, minute=50))
    changed, fits = await app.set_duration(m.id, a.id, 60, True)
    assert not fits
    assert changed.duration_min == 40 and changed.required_duration == 60
    assert (await app.get_appointment(c.id, a.id))[0].start == a.start


async def test_single_duration_change_does_not_change_future_default(setup_app):
    app, m, c, _, b, s, _ = setup_app
    await app.save_service(m.id, b.id, s.name, 2000, "personal", 60, id=s.id)
    a = await app.create(c.id, s.id, stamp(app))
    await app.set_duration(m.id, a.id, 40)
    await app.set_duration(m.id, a.id, 50, False)
    a2 = await app.create(c.id, s.id, stamp(app, day=9))
    assert a2.duration_min == 40


async def test_date_edit_preserves_appointments_and_reports_conflicts(setup_app):
    app, m, c, _, b, s, _ = setup_app
    a = await app.create(c.id, s.id, stamp(app))
    conflicts = await app.edit_schedule(m.id, b.id, a.start.date(), "intervals", intervals("15:00-20:00"))
    assert [x.id for x in conflicts] == [a.id]
    assert (await app.get_appointment(c.id, a.id))[0].status == "booked"


async def test_cross_tenant_and_client_access_denied(setup_app):
    app, m, c, other, b, s, _ = setup_app
    a = await app.create(c.id, s.id, stamp(app))
    with pytest.raises(RuleError):
        await app.get_appointment(other.id, a.id)
    with pytest.raises(RuleError):
        await app.update_business(other.id, b.id, "name", "hijack")
    with pytest.raises(RuleError):
        await app.create(other.id, s.id, stamp(app, hour=12), client_name="Manual")
    with pytest.raises(RuleError):
        await app.set_duration(c.id, a.id, 60)


async def test_manual_card_and_booking(setup_app):
    app, m, c, _, b, s, _ = setup_app
    a = await app.create(m.id, s.id, stamp(app), client_name="Клиент по телефону", duration=50)
    assert a.duration_min == 50
    async with app.repo.transaction() as tx:
        card = await tx.get(Client, a.client_id)
    assert card.user_id is None
    with pytest.raises(RuleError):
        await app.create(m.id, s.id, stamp(app), client_name="Другой клиент", duration=50)


async def test_expired_reservation_releases_time(setup_app):
    app, m, c, other, b, s, clock = setup_app
    await app.save_service(m.id, b.id, s.name, 2000, "personal", 60, id=s.id)
    a = await app.create(c.id, s.id, stamp(app))
    clock[0] += timedelta(minutes=31)
    await app.tick()
    assert (await app.get_appointment(c.id, a.id))[0].status == "expired"
    assert stamp(app) in await app.times(other.id, s.id, date(2026, 9, 8))


async def test_manual_payment_verified_by_owner_only(setup_app):
    app, m, c, other, b, s, _ = setup_app
    await app.update_business(m.id, b.id, "payment_details", "Реквизиты мастера")
    await app.save_service(m.id, b.id, s.name, 2000, "fixed", 40, 500, id=s.id)
    a = await app.create(c.id, s.id, stamp(app))
    assert a.status == "pending_payment"
    await app.payment(c.id, a.id)
    with pytest.raises(RuleError):
        await app.payment(c.id, a.id, True)
    await app.payment(m.id, a.id, True)
    assert (await app.get_appointment(c.id, a.id))[0].status == "booked"


async def test_comments_and_specific_address(setup_app):
    app, m, c, _, b, s, _ = setup_app
    await app.edit_schedule(m.id, b.id, 1, "comment", "По вторникам кабинет 4")
    await app.edit_schedule(m.id, b.id, date(2026, 9, 8), "comment", "Сегодня вход со двора")
    await app.edit_schedule(m.id, b.id, date(2026, 9, 8), "address", "Адрес даты")
    await app.set_time_note(m.id, b.id, date(2026, 9, 8), 600, "Позвоните", "Адрес времени")
    a = await app.create(c.id, s.id, stamp(app))
    _, _, _, address, comment = await app.get_appointment(c.id, a.id)
    assert address == "Адрес времени"
    assert all(x in comment for x in ("Приходите заранее", "По вторникам", "Сегодня", "Позвоните"))


async def test_reminder_tick_idempotent(setup_app):
    app, m, c, _, b, s, clock = setup_app
    a = await app.create(c.id, s.id, stamp(app))
    clock[0] = a.start - timedelta(hours=23)
    await app.tick()
    async with app.repo.transaction() as tx:
        count = len(await tx.list(Notification))
    await app.tick()
    async with app.repo.transaction() as tx:
        assert len(await tx.list(Notification)) == count
