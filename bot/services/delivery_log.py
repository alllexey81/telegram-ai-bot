import datetime
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from bot.config import settings
from bot.database.models import DeliveryLog


async def record_delivery(user_id: int, source: str, goal_text: str | None = None,
                          success: bool = True, error: object = None):
    """Записывает факт отправки (или ошибки) в delivery_log.
    Использует свой движок на вызов - безопасно и из бота, и из Celery, и из админ-веба."""
    engine = create_async_engine(settings.DATABASE_URL, echo=False)
    S = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    try:
        async with S() as session:
            session.add(DeliveryLog(
                user_id=user_id,
                sent_at=datetime.datetime.utcnow(),
                source=source,
                goal_text=(goal_text or "")[:500],
                success=1 if success else 0,
                error=(str(error) or None)[:500],
            ))
            await session.commit()
    finally:
        await engine.dispose()
