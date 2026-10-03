import enum
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
