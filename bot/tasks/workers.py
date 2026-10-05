import asyncio
from datetime import datetime
import pytz
from bot.tasks.celery_app import celery
from bot.config import settings
from bot.database.models import User, SubStatus
from bot.services.ai_services import generate_prompt_and_affirmation, generate_image_with_face
from sqlalchemy.future import select
from sqlalchemy.orm import selectinload
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from aiogram import Bot
import random

bot = Bot(token=settings.BOT_TOKEN)

# Celery-задачи создают новый event loop при каждом запуске (asyncio.run),
# поэтому глобальный движок из crud здесь использовать нельзя - создаем свой
# на каждую задачу и закрываем (иначе: "Future attached to a different loop").
def _task_sessionmaker():
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    return engine, async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _send_morning_affirmations():
    now_utc = datetime.utcnow()
    engine, session_factory = _task_sessionmaker()

    try:
        async with session_factory() as session:
            result = await session.execute(
                select(User).where(User.subscription_status.in_([SubStatus.active, SubStatus.trial]))
                .options(selectinload(User.goals), selectinload(User.photos))
            )
            users = result.scalars().all()

            for user in users:
                try:
                    if not user.timezone or not user.delivery_time:
                        continue
                    tz = pytz.timezone(user.timezone)
                    now_local = now_utc.replace(tzinfo=pytz.utc).astimezone(tz)

                    if now_local.hour == user.delivery_time.hour and now_local.minute == user.delivery_time.minute:
                        if not user.goals:
                            continue

                        goal = random.choice(user.goals)
                        photos = [p.s3_url for p in user.photos]

                        gender = user.gender or "male"
                        ai_data = await generate_prompt_and_affirmation(goal.goal_text, gender)
                        image_url = await generate_image_with_face(
                            ai_data['prompt'], ai_data['affirmation'], photos, gender)

                        # КРИТИЧЕСКОЕ ТРЕБОВАНИЕ ПРОДУКТА: пустой caption
                        await bot.send_photo(chat_id=user.telegram_id, photo=image_url, caption="")

                        # Фиксируем время последней генерации (для кулдауна тестовой)
                        user.last_generation_at = datetime.utcnow()
                        await session.commit()
                except Exception as e:
                    print(f"Error processing user {user.telegram_id}: {e}")
    finally:
        await engine.dispose()


@celery.task
def send_morning_affirmations():
    asyncio.run(_send_morning_affirmations())


async def _check_subscriptions():
    engine, session_factory = _task_sessionmaker()

    try:
        async with session_factory() as session:
            result = await session.execute(select(User))
            users = result.scalars().all()
            now = datetime.utcnow()

            for user in users:
                if not user.subscription_end_date:
                    continue

                days_left = (user.subscription_end_date - now).days

                if days_left == 3 and user.subscription_status == SubStatus.active:
                    await bot.send_message(
                        user.telegram_id,
                        "Через 3 дня твой доступ закончится. Чтобы продлить, активируй промокод: /promo КОД")
                elif days_left < 0 and user.subscription_status != SubStatus.expired:
                    user.subscription_status = SubStatus.expired
                    await session.commit()

                if user.subscription_status == SubStatus.expired:
                    await bot.send_message(
                        user.telegram_id,
                        "Твой доступ истёк. Продлить его можно промокодом: отправь /promo КОД\n"
                        "Получить код можно у администратора бота.")
    finally:
        await engine.dispose()


@celery.task
def check_subscriptions():
    asyncio.run(_check_subscriptions())
