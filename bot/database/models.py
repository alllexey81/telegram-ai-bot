import enum
import datetime
from sqlalchemy import Column, Integer, String, BigInteger, Time, Enum, DateTime, ForeignKey
from sqlalchemy.orm import declarative_base, relationship

Base = declarative_base()

class SubStatus(enum.Enum):
    trial = "trial"
    active = "active"
    expired = "expired"

class User(Base):
    __tablename__ = 'users'
    
    telegram_id = Column(BigInteger, primary_key=True)
    username = Column(String, nullable=True)
    timezone = Column(String, nullable=True)
    delivery_time = Column(Time, nullable=True)
    subscription_status = Column(Enum(SubStatus), default=SubStatus.trial)
    subscription_end_date = Column(DateTime, nullable=True)
    # Пол пользователя: male/female - влияет на состав семьи в генерациях
    gender = Column(String, nullable=True)
    # Индивидуальные требования пользователя к промпту (напр. "без детей", "только мужчины")
    prompt_extra = Column(String, nullable=True)
    last_generation_at = Column(DateTime, nullable=True)

    photos = relationship("Photo", back_populates="user", cascade="all, delete-orphan")
    goals = relationship("Goal", back_populates="user", cascade="all, delete-orphan")

class Photo(Base):
    __tablename__ = 'photos'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey('users.telegram_id'))
    s3_url = Column(String, nullable=False)

    user = relationship("User", back_populates="photos")

class Goal(Base):
    __tablename__ = 'goals'
    
    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey('users.telegram_id'))
    goal_text = Column(String, nullable=False)

    user = relationship("User", back_populates="goals")


class PromoCode(Base):
    """Одноразовый промокод: активирует подписку на days дней первому использовавшему."""
    __tablename__ = 'promo_codes'
    id = Column(Integer, primary_key=True, autoincrement=True)
    code = Column(String, unique=True, nullable=False)
    days = Column(Integer, nullable=False, default=30)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    used_by = Column(BigInteger, nullable=True)
    used_at = Column(DateTime, nullable=True)


class DeliveryLog(Base):
    """Лог всех отправок картинок: рассылка, тестовая генерация, ручная отправка из админки."""
    __tablename__ = 'delivery_log'

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(BigInteger, ForeignKey('users.telegram_id'), nullable=False)
    sent_at = Column(DateTime, default=datetime.datetime.utcnow)
    source = Column(String, nullable=False, default="daily")  # daily / test / manual
    goal_text = Column(String, nullable=True)
    success = Column(Integer, nullable=False, default=1)  # 1 успех, 0 ошибка
    error = Column(String, nullable=True)
    # Путь к сгенерированной картинке (относительно /app/photos) для просмотра в админке
    image_path = Column(String, nullable=True)
    # Финальный промпт, по которому рисовалась картинка
    prompt_text = Column(String, nullable=True)
