import datetime

from sqlalchemy import Column, Date, Integer, String, \
    ForeignKey, DateTime, Boolean, BigInteger
from sqlalchemy.orm import relationship

from database import Base


class Token(Base):
    __tablename__ = "token"

    id = Column(Integer, primary_key=True)
    value = Column(String(100))
    valid_until = Column(Date)

    def __init__(self, value, valid_until):
        self.value = value
        self.valid_until = valid_until


class User(Base):
    __tablename__ = "user"

    tg_id = Column(Integer, primary_key=True)
    token_id = Column(Integer, ForeignKey('token.id'))
    token = relationship('Token')
    api_id = Column(Integer)
    api_hash = Column(String(100))
    is_admin = Column(Boolean, default=False)

    def __init__(self, tg_id, token=None):
        self.tg_id = tg_id
        self.token = token


class TelegramSession(Base):
    __tablename__ = "telegram_session"

    id = Column(Integer, primary_key=True)
    phone_number = Column(String(50))
    phone_code_hash = Column(String(100))
    created_at = Column(DateTime, default=datetime.datetime.now)
    active = Column(Boolean, default=False)
    user_id = Column(Integer, ForeignKey('user.tg_id'))
    user = relationship('User')

    def __init__(self, phone_number, phone_code_hash, user):
        self.phone_number = phone_number
        self.phone_code_hash = phone_code_hash
        self.user = user


class Task(Base):
    __tablename__ = "task"

    id = Column(Integer, primary_key=True)
    message = Column(String(500))
    interval = Column(Integer)
    created_at = Column(DateTime, default=datetime.datetime.now)
    active = Column(Boolean, default=False)
    last_message_date = Column(DateTime)
    user_id = Column(Integer, ForeignKey('user.tg_id'))
    user = relationship('User')
    session_id = Column(Integer, ForeignKey('telegram_session.id'))
    session = relationship('TelegramSession')

    def __init__(self, user, session, message=None, interval=None):
        self.user = user
        self.session = session
        self.message = message
        self.interval = interval


class TelegramGroup(Base):
    __tablename__ = "telegram_group"

    id = Column(Integer, primary_key=True)
    title = Column(String(255))
    tg_id = Column(BigInteger)
    task_id = Column(Integer, ForeignKey('task.id'))
    task = relationship('Task')

    def __init__(self, title, tg_id, task):
        self.title = title
        self.tg_id = tg_id
        self.task = task
