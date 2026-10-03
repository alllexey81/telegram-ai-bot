from aiogram import Router, F, Bot
from aiogram.types import Message
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from datetime import datetime, timedelta
import io
import uuid
from bot.database.crud import async_session, get_user, create_user
from bot.database.models import SubStatus, Photo, Goal
from bot.services.s3_service import upload_photo

router = Router()

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
            
    await message.answer("Привет! У тебя активирован Trial на 1 день. Отправь мне 5-10 своих фотографий (лицо крупным планом).")
    await state.set_state(Onboarding.photos)

@router.message(Onboarding.photos, F.photo)
async def process_photos(message: Message, state: FSMContext, bot: Bot):
    photo = message.photo[-1]
    file = await bot.get_file(photo.file_id)
    file_bytes = io.BytesIO()
    await bot.download_file(file.file_path, file_bytes)
    
    filename = f"{message.from_user.id}/{uuid.uuid4()}.jpg"
    try:
        s3_url = await upload_photo(file_bytes.getvalue(), filename)
    except Exception:
        s3_url = f"https://fake-s3-url/{filename}" # Fallback для локального тестирования без S3
    
    async with async_session() as session:
        p = Photo(user_id=message.from_user.id, s3_url=s3_url)
        session.add(p)
        await session.commit()
        
    await message.answer("Фото загружено. Отправь список своих целей (до 10, можно одним текстом).")
    await state.set_state(Onboarding.goals)

@router.message(Onboarding.goals, F.text)
async def process_goals(message: Message, state: FSMContext):
    goals_list = [g.strip() for g in message.text.split('\n') if g.strip()]
    
    async with async_session() as session:
        for g in goals_list:
            session.add(Goal(user_id=message.from_user.id, goal_text=g))
        await session.commit()
        
    await message.answer("Отлично! Напиши свой часовой пояс (например, Europe/Moscow) и время доставки в формате HH:MM (например, 09:00).")
    await state.set_state(Onboarding.timezone)

@router.message(Onboarding.timezone, F.text)
async def process_timezone(message: Message, state: FSMContext):
    try:
        tz_str, time_str = message.text.split()
        delivery_time = datetime.strptime(time_str, "%H:%M").time()
        
        async with async_session() as session:
            user = await get_user(session, message.from_user.id)
            user.timezone = tz_str
            user.delivery_time = delivery_time
            await session.commit()
            
        await message.answer("Всё настроено! Завтра жди свою первую аффирмацию.")
        await state.clear()
    except Exception:
        await message.answer("Ошибка формата. Попробуй еще раз (Europe/Moscow 09:00)")
