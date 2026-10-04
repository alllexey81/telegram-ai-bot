import datetime

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message

from bot.config import settings
from bot.database.crud import async_session, get_user
from bot.database.models import SubStatus

router = Router()


def _promo_days(code: str) -> int | None:
    """Ищет код в settings.PROMO_CODES ('КОД:дни,...'). Возвращает число дней или None."""
    code = code.strip().upper()
    for pair in settings.PROMO_CODES.split(","):
        pair = pair.strip()
        if ":" not in pair:
            continue
        pcode, _, days = pair.partition(":")
        if pcode.strip().upper() == code and days.strip().isdigit():
            return int(days)
    return None


@router.message(Command("promo"))
async def promo_cmd(message: Message):
    """Активация бесплатной подписки по секретному промокоду: /promo КОД."""
    parts = (message.text or "").split()
    if len(parts) != 2:
        await message.answer("Формат: /promo КОД")
        return

    days = _promo_days(parts[1])
    if not days:
        await message.answer("Промокод не найден или истёк. Проверьте написание.")
        return

    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            await message.answer("Сначала запустите бота: /start")
            return
        base = user.subscription_end_date or datetime.datetime.utcnow()
        if base < datetime.datetime.utcnow():
            base = datetime.datetime.utcnow()
        user.subscription_end_date = base + datetime.timedelta(days=days)
        user.subscription_status = SubStatus.active
        await session.commit()

    await message.answer(
        f"✅ Промокод принят! Бесплатная подписка активна ещё {days} дн. (до "
        f"{user.subscription_end_date.strftime('%d.%m.%Y')}).\n"
        "Генерации продолжат приходить по твоему расписанию.")
