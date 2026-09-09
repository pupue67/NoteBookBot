from datetime import date, timedelta

from notebook_bot.logic.rules import intervals
from conftest import stamp


async def test_lunch_and_grid(setup_app):
    app, m, c, _, b, s, _ = setup_app
    times = await app.times(c.id, s.id, date(2026, 9, 8))
    assert stamp(app, hour=12, minute=20) in times
    assert stamp(app, hour=12, minute=30) not in times
    assert stamp(app, hour=13) not in times
    assert stamp(app, hour=15) in times
    assert all(t.minute % 10 == 0 for t in times)


async def test_day_limit_hides_date_and_cancel_reopens(setup_app):
    app, m, c, other, b, s, _ = setup_app
    day = date(2026, 9, 8)
    await app.edit_schedule(m.id, b.id, day, "limit", 1)
    a = await app.create(c.id, s.id, stamp(app))
    assert day not in await app.dates(other.id, s.id)
    await app.cancel(c.id, a.id, a.revision)
    assert day in await app.dates(other.id, s.id)


async def test_date_override_does_not_change_next_week(setup_app):
    app, m, c, _, b, s, _ = setup_app
    day = date(2026, 9, 8)
    await app.edit_schedule(m.id, b.id, day, "day_off", None)
    assert not await app.times(c.id, s.id, day)
    assert await app.times(c.id, s.id, day + timedelta(days=7))


async def test_multiple_closures_and_buffer(setup_app):
    app, m, c, other, b, s, _ = setup_app
    day = date(2026, 9, 8)
    await app.update_business(m.id, b.id, "buffer_min", 20)
    await app.create(c.id, s.id, stamp(app, hour=11))
    await app.edit_schedule(m.id, b.id, day, "closed", intervals("16:00-16:30, 18:00-19:00"))
    times = await app.times(other.id, s.id, day)
    assert stamp(app, hour=10) in times
    assert stamp(app, hour=10, minute=10) not in times
    assert stamp(app, hour=11, minute=40) not in times
    assert stamp(app, hour=12) in times
    assert stamp(app, hour=15, minute=30) not in times
    assert stamp(app, hour=16, minute=30) in times


async def test_notice_horizon_and_pause(setup_app):
    app, m, c, _, b, s, clock = setup_app
    clock[0] = stamp(app, hour=9, minute=30)
    await app.update_business(m.id, b.id, "horizon_days", 2)
    assert stamp(app, hour=11) not in await app.times(c.id, s.id, clock[0].date())
    assert not await app.times(c.id, s.id, date(2026, 9, 11))
    await app.update_business(m.id, b.id, "accepts_new", False)
    assert not await app.dates(c.id, s.id)


async def test_inherited_limit_can_be_removed_for_one_date(setup_app):
    app, m, c, other, b, s, _ = setup_app
    day = date(2026, 9, 8)
    await app.edit_schedule(m.id, b.id, day.weekday(), "limit", 0)
    assert not await app.times(c.id, s.id, day)
    await app.edit_schedule(m.id, b.id, day, "limit", "-")
    assert await app.times(c.id, s.id, day)
