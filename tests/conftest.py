from datetime import datetime
from zoneinfo import ZoneInfo

import pytest

from notebook_bot.logic.booking import BookingService
from notebook_bot.logic.rules import intervals
from notebook_bot.storage import MemoryRepository


@pytest.fixture
async def setup_app():
    zone = ZoneInfo("Asia/Yekaterinburg")
    clock = [datetime(2026, 9, 7, 8, tzinfo=zone)]
    app = BookingService(MemoryRepository(), zone, clock=lambda: clock[0])
    master = await app.user(100, "Мастер")
    client = await app.user(200, "Алексей")
    other = await app.user(300, "Мария")
    b = await app.create_business(
        master.id, "Логопед Анна", "Анна", "Занятия", "at_master", "Общий адрес", "Приходите заранее"
    )
    s = await app.save_service(master.id, b.id, "Занятие", 2000, "fixed", 40)
    for weekday in range(7):
        await app.edit_schedule(master.id, b.id, weekday, "intervals", intervals("10:00-13:00, 15:00-20:00"))
    return app, master, client, other, b, s, clock


def stamp(app, day=8, hour=10, minute=0):
    return datetime(2026, 9, day, hour, minute, tzinfo=app.timezone)
