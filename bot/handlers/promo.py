import datetime
import secrets

from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message
from sqlalchemy import select

from bot.config import settings
from bot.database.crud import async_session, get_user
from bot.database.models import PromoCode, SubStatus

router = Router()

# Алфавит без похожих символов (0/O, 1/I/L, V/U) — чтобы коды не путались при вводе
_CODE_ALPHABET = "23456789ABCDEFGHJKMNPQRSTWXYZ"


def _generate_code() -> str:
    chunk = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(4))
    chunk2 = "".join(secrets.choice(_CODE_ALPHABET) for _ in range(4))
    return f"FUTURE-{chunk}-{chunk2}"


def _is_admin(message: Message) -> bool:
    return settings.ADMIN_TELEGRAM_ID != 0 and message.from_user.id == settings.ADMIN_TELEGRAM_ID


@router.message(Command("genpromo"))
async def genpromo_cmd(message: Message):
    """Админ: сгенерировать N одноразовых кодов: /genpromo 5 30 (5 кодов по 30 дней)."""
    if not _is_admin(message):
        return
    parts = (message.text or "").split()
    count = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else 1
    days = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 30
    count = min(count, 50)

    codes = []
    async with async_session() as session:
        for _ in range(count):
            code = _generate_code()
            # Защита от коллизии уникального кода
            while (await session.execute(
                    select(PromoCode).where(PromoCode.code == code))).scalars().first():
                code = _generate_code()
            session.add(PromoCode(code=code, days=days))
            codes.append(code)
        await session.commit()

    await message.answer(
        f"Сгенерировано {len(codes)} одноразовых кодов на {days} дн.:\n\n"
        + "\n".join(f"<code>{c}</code>" for c in codes),
        parse_mode="HTML")


@router.message(Command("promolist"))
async def promolist_cmd(message: Message):
    """Админ: все промокоды и кто какой использовал."""
    if not _is_admin(message):
        return
    async with async_session() as session:
        result = await session.execute(select(PromoCode).order_by(PromoCode.id))
        codes = result.scalars().all()

    if not codes:
        await message.answer("Промокодов пока нет. Создайте: /genpromo 5 30")
        return
    lines = [f"Промокодов: {len(codes)}\n"]
    for c in codes:
        status = f"использован юзером {c.used_by}" if c.used_by else "свободен"
        lines.append(f"<code>{c.code}</code> ({c.days} дн.) — {status}")
    await message.answer("\n".join(lines), parse_mode="HTML")


@router.message(Command("promo"))
async def promo_cmd(message: Message):
    """Одноразовая активация подписки промокодом: /promo КОД."""
    parts = (message.text or "").split()
    if len(parts) != 2:
        await message.answer("Формат: /promo КОД (например: /promo FUTURE-2K7X-9QRT)")
        return
    code = parts[1].strip().upper()

    async with async_session() as session:
        row = (await session.execute(
            select(PromoCode).where(PromoCode.code == code))).scalars().first()
        if not row:
            await message.answer("Промокод не найден. Проверьте написание.")
            return
        if row.used_by:
            await message.answer("Этот промокод уже использован. Он одноразовый.")
            return

        user = await get_user(session, message.from_user.id)
        if not user:
            await message.answer("Сначала запустите бота: /start")
            return

        base = user.subscription_end_date or datetime.datetime.utcnow()
        if base < datetime.datetime.utcnow():
            base = datetime.datetime.utcnow()
        user.subscription_end_date = base + datetime.timedelta(days=row.days)
        user.subscription_status = SubStatus.active
        row.used_by = message.from_user.id
        row.used_at = datetime.datetime.utcnow()
        await session.commit()

    await message.answer(
        f"✅ Промокод принят! Доступ активирован на {row.days} дн. (до "
        f"{user.subscription_end_date.strftime('%d.%m.%Y')}).\n"
        "Генерации продолжат приходить по твоему расписанию.")
