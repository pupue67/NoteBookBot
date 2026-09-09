"""Exercise real Aiogram dispatch/FSM against a fake Telegram session. No network/token."""

from datetime import datetime

from aiogram import Bot
from aiogram.client.session.base import BaseSession
from aiogram.methods import AnswerCallbackQuery, GetMe, SendMessage
from aiogram.types import CallbackQuery, Chat, Message, Update, User

from notebook_bot.main import build_dispatcher
from notebook_bot.models import Business, Service


class FakeSession(BaseSession):
    def __init__(self):
        super().__init__()
        self.sent = []

    async def close(self):
        pass

    async def make_request(self, bot, method, timeout=None):
        if isinstance(method, GetMe):
            return User(id=999, is_bot=True, first_name="Notebook", username="notebook_test_bot")
        if isinstance(method, AnswerCallbackQuery):
            return True
        if isinstance(method, SendMessage):
            self.sent.append(method)
            return Message(
                message_id=len(self.sent),
                date=datetime.now(),
                chat=Chat(id=int(method.chat_id), type="private"),
                text=method.text,
                reply_markup=method.reply_markup,
            )
        raise AssertionError(f"Unexpected Telegram method: {type(method).__name__}")

    async def stream_content(self, *args, **kwargs):
        yield b""


async def test_end_to_end_onboarding_booking_and_reschedule(setup_app):
    app, master, client, _, existing_business, service, _ = setup_app
    session = FakeSession()
    bot = Bot("123456789:" + "x" * 35, session=session)
    dp = build_dispatcher(app)
    sequence = 0

    async def event(uid, value, callback=False):
        nonlocal sequence
        sequence += 1
        u = User(id=uid, is_bot=False, first_name=f"User {uid}")
        message = Message(
            message_id=sequence,
            date=datetime.now(),
            chat=Chat(id=uid, type="private"),
            from_user=u,
            text=value if not callback else "screen",
        )
        update = (
            Update(
                update_id=sequence,
                callback_query=CallbackQuery(
                    id=str(sequence), from_user=u, chat_instance="test", data=value, message=message
                ),
            )
            if callback
            else Update(update_id=sequence, message=message)
        )
        await dp.feed_update(bot, update)
        return session.sent[-1]

    def callback_for(message, label):
        return next(
            button.callback_data
            for row in message.reply_markup.inline_keyboard
            for button in row
            if label in button.text
        )

    # Existing and new users get distinct menu variants.
    menu = await event(100, "/start")
    assert "Логопед Анна" in callback_label_text(menu)
    assert "Создать бизнес" in callback_label_text(menu)
    await event(100, callback_for(menu, "Создать бизнес"), True)
    for value in ("Второй бизнес", "Анна", "Консультации", "3", "-", "-"):
        result = await event(100, value)
    assert "Бизнес создан" in result.text
    menu = await event(100, "/start")
    assert "Мои бизнесы:" in menu.text
    assert "Создать бизнес" not in callback_label_text(menu)
    first_profile = await event(100, callback_for(menu, "Логопед Анна"), True)
    assert f"services:{existing_business.id}" == callback_for(first_profile, "Услуги")
    second_profile = await event(100, callback_for(menu, "Второй бизнес"), True)
    assert "Пока нет услуг" in second_profile.text
    assert callback_for(second_profile, "Услуги") != callback_for(first_profile, "Услуги")
    stale = await event(100, "nav:create", True)
    assert "не более двух" in stale.text
    menu = await event(400, "/start")
    assert "Создать бизнес" in callback_label_text(menu)
    await event(400, "nav:create", True)
    for value in ("Новый кабинет", "Ольга", "Индивидуальные занятия", "1", "Новый адрес", "-"):
        result = await event(400, value)
    assert "Бизнес создан" in result.text
    user = await app.user(400, "Ольга")
    async with app.repo.transaction() as tx:
        new_business = (await tx.list(Business, owner_id=user.id))[0]
    await event(400, f"serviceadd:{new_business.id}", True)
    for value in ("Консультация", "1000", "1", "45", "0"):
        result = await event(400, value)
    assert "Услуга сохранена" in result.text
    async with app.repo.transaction() as tx:
        assert len(await tx.list(Service, business_id=new_business.id)) == 1
    await event(400, f"sched:{new_business.id}:w1:intervals", True)
    result = await event(400, "10:00-13:00, 15:00-20:00")
    assert "Изменения сохранены" in result.text
    # Client opens a link and books fixed-duration service through date/time buttons.
    profile = await event(200, f"/start b_{existing_business.id}")
    assert "Записаться" in callback_label_text(profile)
    choices = await event(200, f"bookservice:{service.id}", True)
    day_button = callback_for(choices, "08.09.2026")
    times = await event(200, day_button, True)
    # A previous view's button is rejected after a new view has been shown.
    stale = await event(200, day_button, True)
    assert "устарел" in stale.text
    details = await event(200, callback_for(times, "10:00"), True)
    assert "Общий адрес" in details.text
    booked = await event(200, callback_for(details, "Создать запись"), True)
    assert "Вы записаны" in booked.text
    a = (await app.appointments(client.id))[0]
    await event(100, f"requestmove:{a.id}", True)
    dates = await event(200, f"move:{a.id}", True)
    times = await event(200, callback_for(dates, "09.09.2026"), True)
    assert "сразу применит" in times.text
    moved = await event(200, callback_for(times, "15:00"), True)
    assert "09.09.2026 15:00" in moved.text
    cancel = await event(200, callback_for(moved, "Отменить запись"), True)
    cancelled = await event(200, callback_for(cancel, "Да, отменить"), True)
    assert "Отменена клиентом" in cancelled.text
    await dp.storage.close()
    await bot.session.close()


def callback_label_text(message):
    return " ".join(button.text for row in message.reply_markup.inline_keyboard for button in row)
