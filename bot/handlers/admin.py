import datetime
from pathlib import Path

import pytz
from aiogram import Router
from aiogram.filters import Command
from aiogram.types import Message, FSInputFile
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload

from bot.config import settings
from bot.database.crud import async_session
from bot.database.models import User, Photo, Goal, SubStatus

router = Router()

PHOTOS_DIR = Path("/app/photos")


def _is_admin(message: Message) -> bool:
    return settings.ADMIN_TELEGRAM_ID != 0 and message.from_user.id == settings.ADMIN_TELEGRAM_ID


@router.message(Command("admin"))
async def admin_list(message: Message):
    """Сводка по всем пользователям бота."""
    if not _is_admin(message):
        return
    async with async_session() as session:
        result = await session.execute(
            select(User).options(selectinload(User.goals), selectinload(User.photos)))
        users = result.scalars().all()

    if not users:
        await message.answer("Пользователей пока нет.")
        return

    lines = [f"Пользователей: {len(users)}\n"]
    for u in users:
        tz = u.timezone or "-"
        local_time = "-"
        if u.timezone and u.delivery_time:
            now_local = datetime.datetime.utcnow().replace(
                tzinfo=pytz.utc).astimezone(pytz.timezone(u.timezone))
            local_time = f"{now_local.strftime('%H:%M')} (доставка в {u.delivery_time.strftime('%H:%M')})"
        lines.append(
            f"ID: {u.telegram_id} (@{u.username or 'нет'})\n"
            f"  Подписка: {u.subscription_status.value}, до {u.subscription_end_date or '-'}\n"
            f"  Таймзона: {tz}, {local_time}\n"
            f"  Фото: {len(u.photos)}, целей: {len(u.goals)}\n"
            f"  Детали: /admin_user {u.telegram_id}")
    await message.answer("\n".join(lines))


@router.message(Command("admin_user"))
async def admin_user_details(message: Message):
    """Фотографии и цели конкретного пользователя: /admin_user <telegram_id>."""
    if not _is_admin(message):
        return
    parts = (message.text or "").split()
    if len(parts) != 2 or not parts[1].lstrip("-").isdigit():
        await message.answer("Формат: /admin_user <telegram_id>")
        return
    user_id = int(parts[1])

    async with async_session() as session:
        u_result = await session.execute(
            select(User).where(User.telegram_id == user_id)
            .options(selectinload(User.goals), selectinload(User.photos)))
        user = u_result.scalars().first()
        if not user:
            await message.answer(f"Пользователь {user_id} не найден.")
            return
        goals = [g.goal_text for g in user.goals]
        photos = [p.s3_url for p in user.photos]

    text = (
        f"Пользователь {user_id} (@{user.username or 'нет'})\n"
        f"Подписка: {user.subscription_status.value}\n"
        f"Таймзона: {user.timezone or '-'}\n"
        f"Время доставки: {user.delivery_time or '-'}\n\n"
        f"Цели ({len(goals)}):\n" + ("\n".join(f"  - {g}" for g in goals) if goals else "  (нет)") + "\n\n"
        f"Фото-референсы ({len(photos)}):")
    await message.answer(text)

    # Отправляем сами файлы референсов, чтобы админ видел актуальные лица
    for url in photos[:5]:
        fname = url.split("/")[-1]
        fpath = PHOTOS_DIR / fname
        if fpath.exists():
            await message.answer_photo(FSInputFile(fpath))
        else:
            await message.answer(f"Файл не найден на диске: {fname}")
