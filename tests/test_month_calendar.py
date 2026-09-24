"""Конечная дата календаря ограничивает реальную доступность слотов."""

from datetime import date, timedelta

import pytest

from notebook_bot.bot.calendar import show_month
from notebook_bot.logic.rules import RuleError


async def test_last_booking_day_filters_dates_and_times(setup_app):
    app, master, client, _, business, service, _ = setup_app
    last_day = date(2026, 9, 8)

    await app.set_booking_until(master.id, business.id, last_day)

    assert (await app.business(business.id)).booking_until == last_day
    assert await app.dates(client.id, service.id) == [date(2026, 9, 7), last_day]
    assert await app.times(client.id, service.id, last_day)
    assert await app.times(client.id, service.id, last_day + timedelta(days=1)) == []

    await app.set_booking_until(master.id, business.id, None)
    assert last_day + timedelta(days=1) in await app.dates(client.id, service.id)


async def test_only_owner_can_change_calendar_and_range_is_bounded(setup_app):
    app, master, client, _, business, _, _ = setup_app

    with pytest.raises(RuleError):
        await app.set_booking_until(client.id, business.id, date(2026, 9, 8))
    with pytest.raises(RuleError):
        await app.set_booking_until(master.id, business.id, date(2027, 9, 8))

    class Event:
        pass

    with pytest.raises(RuleError):
        await show_month(Event(), app, master.id, business.id, 2026, 8)
