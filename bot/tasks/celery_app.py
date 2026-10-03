from celery import Celery
from bot.config import settings

celery = Celery(
    "bot_tasks",
    broker=settings.REDIS_URL,
    include=["bot.tasks.workers"]
)

celery.conf.beat_schedule = {
    'daily-morning-delivery': {
        'task': 'bot.tasks.workers.send_morning_affirmations',
        'schedule': 60.0,
    },
    'daily-subscription-check': {
        'task': 'bot.tasks.workers.check_subscriptions',
        'schedule': 86400.0,
    }
}
celery.conf.timezone = 'UTC'
