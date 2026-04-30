"""
Репозиторий для работы с базой данных
🔒 Защита от SQL-инъекций через SQLAlchemy ORM
"""

import logging
import re
from typing import Optional, List, Dict
from datetime import datetime
from contextlib import contextmanager

from sqlalchemy import create_engine, desc
from sqlalchemy.orm import sessionmaker, Session

from database.models import Base, User, Ticket, BotState, WebhookEvent

logger = logging.getLogger(__name__)


# =============================================================================
# 🔒 ВАЛИДАЦИЯ ВХОДНЫХ ДАННЫХ
# =============================================================================

def sanitize_string(value: str, max_length: int = 255) -> str:
    """🔒 Очистка строки от потенциально опасных символов"""
    if not value:
        return ""
    value = value.replace('\x00', '')
    value = value[:max_length]
    return value.strip()


def validate_login(login: str) -> bool:
    """🔒 Проверка логина (только буквы, цифры, точка, подчёркивание, @)"""
    if not login or len(login) > 255:
        return False
    pattern = r'^[a-zA-Z0-9._@-]+$'
    return bool(re.match(pattern, login))


def validate_password(password: str) -> bool:
    """🔒 Проверка пароля (минимум 4 символа)"""
    return bool(password and len(password) >= 4)


# =============================================================================
# БАЗА ДАННЫХ
# =============================================================================

class Database:
    """Управление подключением к БД"""

    def __init__(self, db_url: str = "sqlite:///bot.db"):
        self.engine = create_engine(
            db_url,
            echo=False,
            connect_args={"check_same_thread": False}
        )
        self.SessionLocal = sessionmaker(bind=self.engine)
        self._init_tables()
        logger.info(f"✅ База данных инициализирована: {db_url}")

    def _init_tables(self):
        """Создание таблиц"""
        Base.metadata.create_all(bind=self.engine)

    @contextmanager
    def get_session(self) -> Session:
        """Контекстный менеджер для сессии"""
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"❌ Ошибка БД: {e}")
            raise
        finally:
            session.close()


# =============================================================================
# РЕПОЗИТОРИИ
# =============================================================================

class UserRepository:
    """Операции с пользователями"""

    def __init__(self, db: Database):
        self.db = db

    def create_or_update_user(
        self,
        max_user_id: int,
        chat_id: int,
        zammad_user_id: int,
        zammad_login: str,
        first_name: Optional[str] = None,
        last_name: Optional[str] = None,
        is_authenticated: bool = True,
    ) -> Dict:
        """Создать или обновить пользователя"""
        # 🔒 Валидация
        max_user_id = int(max_user_id)
        chat_id = int(chat_id)
        zammad_user_id = int(zammad_user_id)
        zammad_login = sanitize_string(zammad_login, 255)
        first_name = sanitize_string(first_name, 100) if first_name else None
        last_name = sanitize_string(last_name, 100) if last_name else None

        with self.db.get_session() as session:
            user = session.query(User).filter(User.max_user_id == max_user_id).first()

            if user:
                user.zammad_user_id = zammad_user_id
                user.zammad_login = zammad_login
                user.chat_id = chat_id
                user.is_authenticated = is_authenticated
                user.last_login_at = datetime.utcnow()
                user.updated_at = datetime.utcnow()
                if first_name:
                    user.first_name = first_name
                if last_name:
                    user.last_name = last_name

                logger.info(f"🔒 Обновлён пользователь: max_id={max_user_id}")

                return {
                    'id': user.id,
                    'max_user_id': user.max_user_id,
                    'zammad_user_id': user.zammad_user_id,
                    'zammad_login': user.zammad_login,
                    'is_authenticated': user.is_authenticated,
                    'chat_id': user.chat_id,
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                }
            else:
                user = User(
                    max_user_id=max_user_id,
                    chat_id=chat_id,
                    zammad_user_id=zammad_user_id,
                    zammad_login=zammad_login,
                    first_name=first_name,
                    last_name=last_name,
                    is_authenticated=is_authenticated,
                    is_active=True,
                    created_at=datetime.utcnow(),
                    last_login_at=datetime.utcnow(),
                )
                session.add(user)

                logger.info(f"🔒 Создан пользователь: max_id={max_user_id}")

                return {
                    'id': user.id,
                    'max_user_id': user.max_user_id,
                    'zammad_user_id': user.zammad_user_id,
                    'zammad_login': user.zammad_login,
                    'is_authenticated': user.is_authenticated,
                    'chat_id': user.chat_id,
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                }

    def get_by_max_id(self, max_user_id: int) -> Optional[Dict]:
        """Получить пользователя по MAX user_id"""
        max_user_id = int(max_user_id)

        with self.db.get_session() as session:
            user = session.query(User).filter(User.max_user_id == max_user_id).first()

            if user:
                return {
                    'id': user.id,
                    'max_user_id': user.max_user_id,
                    'zammad_user_id': user.zammad_user_id,
                    'zammad_login': user.zammad_login,
                    'is_authenticated': user.is_authenticated,
                    'chat_id': user.chat_id,
                    'first_name': user.first_name,
                    'last_name': user.last_name,
                }
            return None

    def get_by_zammad_id(self, zammad_user_id: int) -> Optional[Dict]:
        """Получить пользователя по Zammad user_id"""
        zammad_user_id = int(zammad_user_id)

        with self.db.get_session() as session:
            user = session.query(User).filter(User.zammad_user_id == zammad_user_id).first()

            if user:
                return {
                    'id': user.id,
                    'max_user_id': user.max_user_id,
                    'zammad_user_id': user.zammad_user_id,
                    'zammad_login': user.zammad_login,
                    'is_authenticated': user.is_authenticated,
                    'chat_id': user.chat_id,
                }
            return None

    def is_authenticated(self, max_user_id: int) -> bool:
        """Проверить авторизован ли пользователь"""
        user = self.get_by_max_id(max_user_id)
        return bool(user and user.get('is_authenticated'))

    def logout(self, max_user_id: int):
        """Отвязать аккаунт"""
        max_user_id = int(max_user_id)

        with self.db.get_session() as session:
            session.query(User).filter(User.max_user_id == max_user_id).update({
                "zammad_user_id": None,
                "zammad_login": None,
                "is_authenticated": False,
                "updated_at": datetime.utcnow(),
            })
            logger.info(f"🔒 Пользователь {max_user_id} вышел из аккаунта")


class TicketRepository:
    """Операции с заявками"""

    def __init__(self, db: Database):
        self.db = db

    def sync_ticket(
        self,
        zammad_ticket_id: int,
        zammad_ticket_number: str,
        user_id: int,
        **kwargs
    ) -> Dict:
        """Синхронизировать тикет из Zammad в БД"""
        zammad_ticket_id = int(zammad_ticket_id)
        user_id = int(user_id)
        zammad_ticket_number = sanitize_string(str(zammad_ticket_number), 50)

        with self.db.get_session() as session:
            ticket = session.query(Ticket).filter(Ticket.zammad_ticket_id == zammad_ticket_id).first()

            if ticket:
                ticket.state = sanitize_string(kwargs.get('state', ticket.state), 50)
                ticket.state_id = kwargs.get('state_id')
                ticket.title = sanitize_string(kwargs.get('title', ticket.title), 500)
                ticket.priority = sanitize_string(kwargs.get('priority', ticket.priority), 50)
                ticket.group_name = sanitize_string(kwargs.get('group_name', ticket.group_name), 100)
                ticket.updated_at = datetime.utcnow()
            else:
                ticket = Ticket(
                    zammad_ticket_id=zammad_ticket_id,
                    zammad_ticket_number=zammad_ticket_number,
                    user_id=user_id,
                    title=sanitize_string(kwargs.get('title', ''), 500),
                    state=sanitize_string(kwargs.get('state', 'new'), 50),
                    state_id=kwargs.get('state_id'),
                    priority=sanitize_string(kwargs.get('priority', ''), 50),
                    group_name=sanitize_string(kwargs.get('group_name', ''), 100),
                )
                session.add(ticket)

            return {
                'id': ticket.id,
                'zammad_ticket_id': ticket.zammad_ticket_id,
                'zammad_ticket_number': ticket.zammad_ticket_number,
                'user_id': ticket.user_id,
                'state': ticket.state,
                'state_id': ticket.state_id,
            }

    def get_user_tickets(self, user_id: int, limit: int = 10) -> List[Dict]:
        """Получить заявки пользователя"""
        user_id = int(user_id)
        limit = min(int(limit), 100)

        with self.db.get_session() as session:
            tickets = session.query(Ticket).filter(Ticket.user_id == user_id)\
                .order_by(desc(Ticket.created_at)).limit(limit).all()

            return [{
                'id': t.id,
                'zammad_ticket_id': t.zammad_ticket_id,
                'zammad_ticket_number': t.zammad_ticket_number,
                'title': t.title,
                'state': t.state,
                'state_id': t.state_id,
                'priority': t.priority,
                'group_name': t.group_name,
                'created_at': t.created_at.isoformat() if t.created_at else None,
                'updated_at': t.updated_at.isoformat() if t.updated_at else None,
            } for t in tickets]

    def get_user_tickets_by_state(self, user_id: int, state_ids: List[int], limit: int = 10) -> List[Dict]:
        """Получить заявки пользователя по статусам"""
        user_id = int(user_id)
        limit = min(int(limit), 100)
        state_ids = [int(s) for s in state_ids]

        with self.db.get_session() as session:
            tickets = session.query(Ticket).filter(
                Ticket.user_id == user_id,
                Ticket.state_id.in_(state_ids)
            ).order_by(desc(Ticket.created_at)).limit(limit).all()

            return [{
                'id': t.id,
                'zammad_ticket_id': t.zammad_ticket_id,
                'zammad_ticket_number': t.zammad_ticket_number,
                'title': t.title,
                'state': t.state,
                'state_id': t.state_id,
                'priority': t.priority,
                'group_name': t.group_name,
                'created_at': t.created_at.isoformat() if t.created_at else None,
                'updated_at': t.updated_at.isoformat() if t.updated_at else None,
            } for t in tickets]

    def get_by_zammad_id(self, zammad_ticket_id: int) -> Optional[Dict]:
        """Получить тикет по Zammad ID"""
        zammad_ticket_id = int(zammad_ticket_id)

        with self.db.get_session() as session:
            ticket = session.query(Ticket).filter(Ticket.zammad_ticket_id == zammad_ticket_id).first()

            if ticket:
                return {
                    'id': ticket.id,
                    'zammad_ticket_id': ticket.zammad_ticket_id,
                    'zammad_ticket_number': ticket.zammad_ticket_number,
                    'user_id': ticket.user_id,
                    'state': ticket.state,
                    'state_id': ticket.state_id,
                }
            return None

    def get_all_open_tickets(self, limit: int = 100) -> List[Dict]:
        """Получить все открытые заявки"""
        limit = min(int(limit), 100)

        with self.db.get_session() as session:
            tickets = session.query(Ticket).filter(Ticket.state_id.in_([1, 2]))\
                .order_by(desc(Ticket.created_at)).limit(limit).all()

            return [{
                'id': t.id,
                'zammad_ticket_id': t.zammad_ticket_id,
                'zammad_ticket_number': t.zammad_ticket_number,
                'user_id': t.user_id,
                'state': t.state,
                'state_id': t.state_id,
            } for t in tickets]


class BotStateRepository:
    """Операции с состояниями бота"""

    def __init__(self, db: Database):
        self.db = db

    def get(self, key: str, default: Optional[str] = None) -> Optional[str]:
        """Получить значение"""
        key = sanitize_string(key, 100)

        with self.db.get_session() as session:
            state = session.query(BotState).filter(BotState.key == key).first()
            return state.value if state else default

    def set(self, key: str, value: str):
        """Установить значение"""
        key = sanitize_string(key, 100)
        value = sanitize_string(value, 1000)

        with self.db.get_session() as session:
            state = session.query(BotState).filter(BotState.key == key).first()
            if state:
                state.value = value
                state.updated_at = datetime.utcnow()
            else:
                session.add(BotState(key=key, value=value))


class WebhookEventRepository:
    """🔥 Операции с событиями webhook"""

    def __init__(self, db: Database):
        self.db = db

    def log_event(self, event_type: str, ticket_id: int, payload: Dict,
                  article_id: Optional[int] = None, user_id: Optional[int] = None):
        """Записать событие в БД"""
        import json
        with self.db.get_session() as session:
            event = WebhookEvent(
                event_type=event_type,
                zammad_ticket_id=ticket_id,
                zammad_article_id=article_id,
                user_id=user_id,
                payload=json.dumps(payload, ensure_ascii=False),
                processed=False,
                created_at=datetime.utcnow(),
            )
            session.add(event)
            logger.debug(f"📥 Webhook event logged: {event_type} #{ticket_id}")

    def mark_processed(self, event_id: int):
        """Отметить событие как обработанное"""
        with self.db.get_session() as session:
            session.query(WebhookEvent).filter(WebhookEvent.id == event_id).update({
                "processed": True,
                "processed_at": datetime.utcnow(),
            })

    def get_pending_events(self, limit: int = 100) -> List[WebhookEvent]:
        """Получить необработанные события"""
        with self.db.get_session() as session:
            return session.query(WebhookEvent).filter(
                WebhookEvent.processed == False
            ).order_by(WebhookEvent.created_at).limit(limit).all()


# =============================================================================
# ГЛОБАЛЬНЫЕ ЭКЗЕМПЛЯРЫ
# =============================================================================

db: Optional[Database] = None
user_repo: Optional[UserRepository] = None
ticket_repo: Optional[TicketRepository] = None
state_repo: Optional[BotStateRepository] = None
webhook_repo: Optional[WebhookEventRepository] = None


def init_database(db_url: str = "sqlite:///bot.db"):
    """Инициализация базы данных и репозиториев"""
    global db, user_repo, ticket_repo, state_repo, webhook_repo

    db = Database(db_url)
    user_repo = UserRepository(db)
    ticket_repo = TicketRepository(db)
    state_repo = BotStateRepository(db)
    webhook_repo = WebhookEventRepository(db)

    logger.info("✅ Репозитории БД инициализированы")


def get_repos():
    """Получить все репозитории"""
    return {
        'user': user_repo,
        'ticket': ticket_repo,
        'state': state_repo,
        'webhook': webhook_repo,
    }