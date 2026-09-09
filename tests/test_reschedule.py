import pytest

from notebook_bot.logic.rules import RuleError
from conftest import stamp


async def test_master_requests_client_selects_new_date_and_time(setup_app):
    app, m, c, _, b, s, _ = setup_app
    a = await app.create(c.id, s.id, stamp(app))
    with pytest.raises(RuleError):
        await app.move(m.id, a.id, stamp(app, day=9, hour=15), a.revision)
    await app.request_move(m.id, a.id)
    pending = (await app.get_appointment(c.id, a.id))[0]
    assert pending.start == a.start
    moved = await app.move(c.id, a.id, stamp(app, day=9, hour=15), pending.revision)
    assert moved.start == stamp(app, day=9, hour=15) and not moved.move_requested


async def test_failed_move_keeps_old_time(setup_app):
    app, m, c, other, b, s, _ = setup_app
    a = await app.create(c.id, s.id, stamp(app))
    await app.create(other.id, s.id, stamp(app, day=9))
    with pytest.raises(RuleError):
        await app.move(c.id, a.id, stamp(app, day=9), a.revision)
    assert (await app.get_appointment(c.id, a.id))[0].start == a.start


async def test_old_callback_revision_rejected(setup_app):
    app, m, c, _, b, s, _ = setup_app
    a = await app.create(c.id, s.id, stamp(app))
    await app.move(c.id, a.id, stamp(app, day=9), a.revision)
    with pytest.raises(RuleError):
        await app.cancel(c.id, a.id, a.revision)


async def test_move_with_larger_duration_no_trimming(setup_app):
    app, m, c, other, b, s, _ = setup_app
    a = await app.create(c.id, s.id, stamp(app))
    await app.create(other.id, s.id, stamp(app, minute=50))
    a, fits = await app.set_duration(m.id, a.id, 60)
    assert not fits
    await app.request_move(m.id, a.id)
    a = (await app.get_appointment(c.id, a.id))[0]
    a = await app.move(c.id, a.id, stamp(app, day=9, hour=15), a.revision)
    assert a.duration_min == 60
