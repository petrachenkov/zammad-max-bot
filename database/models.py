"""
Модели базы данных для бота
"""

from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Boolean, Index
from sqlalchemy.orm import relationship, declarative_base
from datetime import datetime

Base = declarative_base()


class User(Base):
    """Пользователь MAX Messenger"""
    __tablename__ = 'users'

    id = Column(Integer, primary_key=True, autoincrement=True)
    max_user_id = Column(Integer, unique=True, nullable=False, index=True)
    chat_id = Column(Integer, nullable=False)

    # Zammad аккаунт пользователя
    zammad_user_id = Column(Integer, unique=True, index=True)
    zammad_login = Column(String(255), unique=True, index=True)

    # Профиль
    first_name = Column(String(100))
    last_name = Column(String(100))

    # Статус авторизации
    is_authenticated = Column(Boolean, default=False)
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_login_at = Column(DateTime)

    # Связи
    tickets = relationship("Ticket", back_populates="user", cascade="all, delete-orphan")

    __table_args__ = (
        Index('idx_users_zammad_id', 'zammad_user_id'),
        Index('idx_users_zammad_login', 'zammad_login'),
        Index('idx_users_max_id', 'max_user_id'),
    )

    def __repr__(self):
        return f"<User(max_id={self.max_user_id}, login={self.zammad_login})>"


class Ticket(Base):
    """Заявка Zammad"""
    __tablename__ = 'tickets'

    id = Column(Integer, primary_key=True, autoincrement=True)
    zammad_ticket_id = Column(Integer, unique=True, nullable=False, index=True)
    zammad_ticket_number = Column(String(50), index=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=False, index=True)

    title = Column(String(500))
    state = Column(String(50), default='new')
    state_id = Column(Integer)
    priority = Column(String(50))
    group_name = Column(String(100))

    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    last_sync_at = Column(DateTime)

    user = relationship("User", back_populates="tickets")

    __table_args__ = (
        Index('idx_tickets_zammad_id', 'zammad_ticket_id'),
        Index('idx_tickets_user_id', 'user_id'),
        Index('idx_tickets_state', 'state_id'),
    )


class BotState(Base):
    """Состояния бота"""
    __tablename__ = 'bot_states'

    id = Column(Integer, primary_key=True, autoincrement=True)
    key = Column(String(100), unique=True, nullable=False, index=True)
    value = Column(Text)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class WebhookEvent(Base):
    """🔥 События от Zammad webhook"""
    __tablename__ = 'webhook_events'

    id = Column(Integer, primary_key=True, autoincrement=True)
    event_type = Column(String(100), nullable=False, index=True)
    zammad_ticket_id = Column(Integer, index=True)
    zammad_article_id = Column(Integer, nullable=True)
    user_id = Column(Integer, ForeignKey('users.id'), nullable=True)

    payload = Column(Text)
    processed = Column(Boolean, default=False)

    created_at = Column(DateTime, default=datetime.utcnow)
    processed_at = Column(DateTime, nullable=True)

    __table_args__ = (
        Index('idx_webhook_created', 'created_at'),
        Index('idx_webhook_processed', 'processed'),
    )