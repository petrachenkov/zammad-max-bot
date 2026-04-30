"""
Маппинг MAX ↔ Zammad через БД
"""

import logging
from typing import Optional, Dict, List

from database.repository import get_repos

logger = logging.getLogger(__name__)


class ChatMapper:
    def __init__(self):
        self.repos = get_repos()

    def is_authenticated(self, max_user_id: int) -> bool:
        return self.repos['user'].is_authenticated(max_user_id)

    def get_user(self, max_user_id: int) -> Optional[Dict]:
        return self.repos['user'].get_by_max_id(max_user_id)

    def get_zammad_user_id(self, max_user_id: int) -> Optional[int]:
        user = self.get_user(max_user_id)
        return user.get('zammad_user_id') if user else None

    def get_user_tickets(self, max_user_id: int, limit: int = 10) -> List[Dict]:
        user = self.get_user(max_user_id)
        if not user:
            return []
        return self.repos['ticket'].get_user_tickets(user['id'], limit)

    def get_open_tickets(self, max_user_id: int, limit: int = 10) -> List[Dict]:
        user = self.get_user(max_user_id)
        if not user:
            return []
        return self.repos['ticket'].get_user_tickets_by_state(user['id'], [1, 2], limit)

    def get_closed_tickets(self, max_user_id: int, limit: int = 10) -> List[Dict]:
        user = self.get_user(max_user_id)
        if not user:
            return []
        return self.repos['ticket'].get_user_tickets_by_state(user['id'], [4], limit)

    def sync_tickets(self, max_user_id: int, tickets: List[Dict]):
        """Синхронизировать тикеты из Zammad в БД"""
        user = self.get_user(max_user_id)
        if not user:
            return

        for t in tickets:
            if isinstance(t, dict):
                self.repos['ticket'].sync_ticket(
                    zammad_ticket_id=t.get('id'),
                    zammad_ticket_number=str(t.get('number', t.get('id'))),
                    user_id=user['id'],
                    title=t.get('title', ''),
                    state=t.get('state', 'new'),
                    state_id=t.get('state_id'),
                    priority=t.get('priority'),
                    group_name=t.get('group'),
                )


mapper: Optional[ChatMapper] = None


def init_mapper():
    """Инициализация маппера — вызывать ПОСЛЕ init_database()!"""
    global mapper
    from database.repository import get_repos  # 🔥 Импортируем внутри функции
    mapper = ChatMapper()
    logger.info("✅ ChatMapper инициализирован")


def get_mapper() -> ChatMapper:
    """Получить экземпляр маппера"""
    global mapper
    if mapper is None:
        # 🔥 Если mapper ещё не инициализирован — создаём новый
        from database.repository import get_repos
        mapper = ChatMapper()
    return mapper