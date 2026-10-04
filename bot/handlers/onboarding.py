from aiogram import Router, F, Bot
from aiogram.types import Message
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime, timedelta
import io
import uuid
import random
from sqlalchemy.future import select
from bot.database.crud import async_session, get_user, create_user
from bot.database.models import SubStatus, Photo, Goal
from bot.services.s3_service import upload_photo
from bot.services.ai_services import generate_prompt_and_affirmation, generate_image_with_face

router = Router()

HELP_TEXT = (
    "📖 <b>Инструкция «Фото будущего»</b>\n\n"
    "Каждый день бот присылает тебе персональную картинку: ты — главный герой, сцена — одна из твоих целей.\n\n"
    "<b>Команды:</b>\n"
    "/start — начать работу (онбординг: фото → цели → город и время)\n"
    "/help — показать эту инструкцию\n"
    "/photo — заменить фото-референсы (новое лицо: загрузка 1-5 фото)\n"
    "/goals — изменить список целей (фото и расписание не трогаются)\n"
    "/reset — полный сброс: удалить фото и цели, начать онбординг заново\n\n"
    "<b>Как это работает:</b>\n"
    "• Фото: 1-5 чётких фото лица крупным планом (анфас, вполоборота, разный свет) — чем качественнее, тем выше сходство.\n"
    "• Цели: до 10, можно одним сообщением (разделяй строками, точками или запятыми).\n"
    "• Время: город + время доставки, например «Иркутск 16:20». Ежедневная генерация приходит в это время.\n"
    "• Каждую генерацию бот выбирает случайную цель из твоего списка и новый визуальный стиль (журнальное фото, кадр из кино, иллюстрация и т.д.).\n\n"
    "✏️ Проверить свои данные можно в любой момент: /photo, /goals или /reset."
)


class Onboarding(StatesGroup):
    photos = State()
    goals = State()
    timezone = State()


@router.message(CommandStart())
async def start_cmd(message: Message, state: FSMContext):
    async with async_session() as session:
        user = await get_user(session, message.from_user.id)
        if not user:
            user = await create_user(session, message.from_user.id, message.from_user.username)
            user.subscription_status = SubStatus.trial
            user.subscription_end_date = datetime.utcnow() + timedelta(days=1)
            await session.commit()

    await message.answer(
        "Привет! У тебя активирован Trial на 1 день.\n"
        "Отправь мне от 1 до 5 своих фотографий (лицо крупным планом). Лучше 3-5: анфас, вполоборота, при разном освещении — так сходство будет выше.\n"
        "Когда закончишь — напиши «готово» или сразу пришли список целей.\n\n"
        + HELP_TEXT,
        parse_mode="HTML",
    )
    await state.set_state(Onboarding.photos)


@router.message(Command("reset"))
async def reset_cmd(message: Message, state: FSMContext):
    from sqlalchemy import delete
    async with async_session() as session:
        await session.execute(delete(Goal).where(Goal.user_id == message.from_user.id))
        await session.execute(delete(Photo).where(Photo.user_id == message.from_user.id))
        await session.commit()
    await state.clear()
    await message.answer(
        "Данные очищены. Давай начнём заново: отправь от 1 до 5 своих фотографий (лицо крупным планом, лучше 3-5 разных ракурсов).\n"
        "Когда закончишь — напиши «готово» или сразу пришли список целей.\n\n"
        + HELP_TEXT,
        parse_mode="HTML",
    )
    await state.set_state(Onboarding.photos)


@router.message(Command("help"))
async def help_cmd(message: Message):
    await message.answer(HELP_TEXT, parse_mode="HTML")


@router.message(Command("photo"))
async def replace_photo_cmd(message: Message, state: FSMContext):
    """Замена референс-фото: удаляет старые фото, включает загрузку новых."""
    from sqlalchemy import delete
    async with async_session() as session:
        await session.execute(delete(Photo).where(Photo.user_id == message.from_user.id))
        await session.commit()
    await state.clear()
    await state.set_state(Onboarding.photos)
    await message.answer(
        "Старые фото удалены. Отправь новые фотографии нового лица (1-5, крупным планом, лучше с разных ракурсов).\n"
        "Когда закончишь — напиши «готово» или сразу пришли список целей.")


@router.message(Command("goals"))
async def edit_goals_cmd(message: Message, state: FSMContext):
    """Корректировка целей: удаляет старые, просит новый список. Фото и расписание не трогаем."""
    from sqlalchemy import delete
    async with async_session() as session:
        await session.execute(delete(Goal).where(Goal.user_id == message.from_user.id))
        await session.commit()
    await state.clear()
    await state.set_state(Onboarding.goals)
    await message.answer(
        "Старые цели удалены. Пришли новый список целей (до 10, можно одним текстом — разделяй строками, точками или запятыми).\n"
        "Время и город доставки останутся прежними. Тестовая генерация по новой цели придёт сразу после ввода.")


@router.message(Onboarding.photos, F.photo)
async def process_photos(message: Message, state: FSMContext, bot: Bot):
    async with async_session() as session:
        count_result = await session.execute(
            select(Photo).where(Photo.user_id == message.from_user.id))
        if len(count_result.scalars().all()) >= 5:
            await message.answer(
                "Уже 5 фотографий — этого достаточно.\n"
                "Напиши «готово» или сразу отправь список своих целей (до 10, можно одним текстом).")
            return

    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    file_bytes = io.BytesIO()
    await bot.download_file(file.file_path, file_bytes)

    filename = f"{message.from_user.id}/{uuid.uuid4()}.jpg"
    # upload_photo сохраняет файл локально в /app/photos и возвращает рабочий URL,
    # (S3 не используется). Исключения не должны превращать фото в фейк-ссылку.
    s3_url = await upload_photo(file_bytes.getvalue(), filename)

    async with async_session() as session:
        p = Photo(user_id=message.from_user.id, s3_url=s3_url)
        session.add(p)
        await session.commit()

    await message.answer(
        "Фото загружено. Можешь отправить ещё (до 5 всего) — "
        "или напиши «готово» / сразу список своих целей (до 10, можно одним текстом).")


@router.message(Onboarding.photos, F.text)
async def finish_photos(message: Message, state: FSMContext):
    """Текст в состоянии загрузки фото = пользователь закончил, переходим к целям."""
    await state.set_state(Onboarding.goals)
    await message.answer("Отлично! Отправь список своих целей (до 10, можно одним текстом).")


@router.message(Onboarding.goals, F.text)
async def process_goals(message: Message, state: FSMContext):
    # Разбиваем сообщение на отдельные цели: по новой строке, точке или запятой
    import re
    raw = message.text
    parts = re.split(r'[.\n,;]+', raw)
    goals_list = []
    for part in parts:
        g = part.strip().strip('.').strip()
        # Отбрасываем мусорные фрагменты
        if g and len(g) > 2 and g.lower() not in ('и', 'а', 'или'):
            goals_list.append(g)

    async with async_session() as session:
        for g in goals_list:
            session.add(Goal(user_id=message.from_user.id, goal_text=g))
        await session.commit()

    await message.answer(
        f"Принято целей: {len(goals_list)}.\n"
        "Отлично! Напиши свой город и время доставки в формате HH:MM (например: Иркутск 16:20)."
    )
    await state.set_state(Onboarding.timezone)


@router.message(Onboarding.timezone, F.text)
async def process_timezone(message: Message, state: FSMContext):
    import re
    text = message.text

    time_match = re.search(r'\b([0-9]{1,2}:[0-9]{2})\b', text)
    if not time_match:
        await message.answer("Я не нашел время в твоем сообщении. Напиши, пожалуйста, время в формате HH:MM (например: 16:20)")
        return

    time_str = time_match.group(1)

    try:
        delivery_time = datetime.strptime(time_str, "%H:%M").time()

        tz_str = "Asia/Irkutsk" if "иркутск" in text.lower() else "Europe/Moscow"

        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
            user.timezone = tz_str
            user.delivery_time = delivery_time
            await session.commit()

            goals_result = await session.execute(select(Goal).where(Goal.user_id == message.from_user.id))
            goals = goals_result.scalars().all()

            photos_result = await session.execute(select(Photo).where(Photo.user_id == message.from_user.id))
            photos = photos_result.scalars().all()

        await message.answer(
            f"Всё настроено! Время доставки: {time_str}.\n\n"
            f"⏳ Сейчас сгенерирую для тебя тестовую аффирмацию, подожди немного (генерация занимает время)..."
        )
        await state.clear()

        if goals and photos:
            try:
                goal = random.choice(goals)
                photo_urls = [p.s3_url for p in photos]

                ai_data = await generate_prompt_and_affirmation(goal.goal_text)
                result = await generate_image_with_face(ai_data['prompt'], ai_data['affirmation'], photo_urls)

                # ТЗ: caption должен быть пустым
                from aiogram.types import BufferedInputFile

                if isinstance(result, str):
                    import aiohttp
                    async with aiohttp.ClientSession() as http_session:
                        async with http_session.get(result) as resp:
                            if resp.status == 200:
                                image_bytes = await resp.read()
                                await message.answer_photo(
                                    photo=BufferedInputFile(image_bytes, filename="affirmation.png"), caption="")
                            else:
                                await message.answer(f"Не удалось скачать сгенерированную картинку (HTTP {resp.status}).")
                else:
                    await message.answer_photo(
                        photo=BufferedInputFile(result.image_bytes, filename="affirmation.png"), caption="")
            except Exception as e:
                await message.answer(f"Произошла ошибка при генерации тестовой картинки: {e}")
        else:
            await message.answer("Не удалось найти фото или цели для генерации.")

    except Exception:
        await message.answer("Ошибка формата. Попробуй еще раз (например: Иркутск 16:20)")