"""
Клиент для работы с Zammad API
"""

import logging
import requests
import urllib3
import ssl
from typing import Optional, Dict, Any, List

ssl._create_default_https_context = ssl._create_unverified_context
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

from config import config

logger = logging.getLogger(__name__)

# =============================================================================
# 🔥 КЭШ ПОЛЬЗОВАТЕЛЕЙ
# =============================================================================

zammad_users_cache: Dict[int, Dict[str, str]] = {}


def get_user_from_cache(user_id: int) -> Optional[Dict[str, str]]:
    """Получить пользователя из кэша"""
    return zammad_users_cache.get(user_id)


def set_user_in_cache(user_id: int, user_info: Dict[str, str]):
    """Сохранить пользователя в кэш"""
    zammad_users_cache[user_id] = user_info
    logger.debug(f"💾 User cached: {user_id}")


class ZammadClient:
    """Клиент для работы с Zammad API"""

    def __init__(self):
        self.base_url = config.zammad_url.rstrip('/')
        self.bot_token = config.zammad_token

        self.session = requests.Session()
        self.session.verify = False
        self.session.headers.update({
            "Authorization": f"Token token={self.bot_token}",
            "Content-Type": "application/json",
            "Accept": "application/json"
        })

        logger.info(f"✅ ZammadClient инициализирован: {self.base_url}")

    def _get(self, endpoint: str, params: Dict = None) -> Any:
        url = f"{self.base_url}/api/v1/{endpoint.lstrip('/')}"
        resp = self.session.get(url, params=params, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _post(self, endpoint: str, json: Dict) -> Any:
        url = f"{self.base_url}/api/v1/{endpoint.lstrip('/')}"
        resp = self.session.post(url, json=json, timeout=30)
        resp.raise_for_status()
        return resp.json()

    def _put(self, endpoint: str, json: Dict) -> Any:
        url = f"{self.base_url}/api/v1/{endpoint.lstrip('/')}"
        resp = self.session.put(url, json=json, timeout=30)
        resp.raise_for_status()
        return resp.json()

    async def authenticate_user(self, login: str, password: str) -> Optional[Dict[str, Any]]:
        try:
            import base64

            session = requests.Session()
            session.verify = False

            credentials = base64.b64encode(f"{login}:{password}".encode()).decode()
            session.headers.update({
                "Authorization": f"Basic {credentials}",
                "Content-Type": "application/json",
            })

            url = f"{self.base_url}/api/v1/users/me"
            resp = session.get(url, timeout=10)

            if resp.status_code == 200:
                user_data = resp.json()
                logger.info(f"✅ Аутентификация успешна: {user_data.get('login')}")
                return {
                    'id': user_data.get('id'),
                    'email': user_data.get('email'),
                    'login': user_data.get('login'),
                    'firstname': user_data.get('firstname'),
                    'lastname': user_data.get('lastname'),
                }
            else:
                logger.warning(f"❌ Аутентификация не удалась: {resp.status_code}")
                return None

        except Exception as e:
            logger.error(f"❌ Ошибка аутентификации: {e}")
            return None

    async def get_user(self, user_id: int) -> Optional[Dict[str, Any]]:
        """Получить пользователя по ID"""
        try:
            # Проверяем кэш
            cached = get_user_from_cache(user_id)
            if cached:
                logger.debug(f"💾 User from cache: {user_id}")
                return cached

            # Запрашиваем из API
            user_data = self._get(f"users/{user_id}")

            if user_data:
                user_info = {
                    'firstname': user_data.get('firstname', ''),
                    'lastname': user_data.get('lastname', ''),
                    'login': user_data.get('login', ''),
                }
                set_user_in_cache(user_id, user_info)
                return user_data

            return None
        except Exception as e:
            logger.debug(f"⚠️ Не удалось получить пользователя {user_id}: {e}")
            return None

    async def get_user_tickets(self, user_id: int, limit: int = 50) -> List[Dict]:
        try:
            data = self._get("tickets", params={"per_page": limit})

            tickets = []
            if isinstance(data, list):
                tickets = data
            elif isinstance(data, dict):
                assets = data.get("assets", {})
                ticket_assets = assets.get("Ticket", {})
                if isinstance(ticket_assets, dict):
                    tickets = list(ticket_assets.values())
                elif isinstance(ticket_assets, list):
                    tickets = ticket_assets

            result = [t for t in tickets if isinstance(t, dict) and t.get("customer_id") == user_id]

            if isinstance(data, dict) and "assets" in data:
                user_assets = data["assets"].get("User", {})
                for t in result:
                    if user_assets:
                        t["assets"] = {"User": user_assets}

            logger.debug(f"✅ Получено {len(result)} тикетов для пользователя {user_id}")
            return result

        except Exception as e:
            logger.error(f"❌ Ошибка получения тикетов: {e}")
            return []

    async def create_ticket(self, title: str, body: str, customer_id: int, **kwargs) -> Dict:
        ticket_data = {
            "title": title,
            "group": kwargs.get('group', config.default_group),
            "customer_id": customer_id,
            "state": "new",
            "priority": kwargs.get('priority', config.default_priority),
            "article": {
                "subject": title,
                "body": body,
                "type": "note",
                "internal": False,
                "sender": "Customer",
            }
        }

        result = self._post("tickets", json=ticket_data)
        logger.info(f"✅ Тикет #{result.get('number')} создан")
        return result

    async def add_article(self, ticket_id: int, body: str, **kwargs) -> Dict:
        article_data = {
            "ticket_id": ticket_id,
            "article": {
                "subject": "Re",
                "body": body,
                "type": "note",
                "internal": kwargs.get('internal', False),
                "sender": kwargs.get('sender', 'Customer'),
            }
        }
        result = self._post("ticket_articles", json=article_data)
        logger.info(f"✅ Сообщение добавлено к #{ticket_id}")
        return result

    async def get_ticket(self, ticket_id: int) -> Optional[Dict]:
        try:
            return self._get(f"tickets/{ticket_id}")
        except Exception as e:
            logger.debug(f"⚠️ Не удалось получить тикет {ticket_id}: {e}")
            return None

    async def update_ticket_state(self, ticket_id: int, state: str, note: Optional[str] = None) -> Dict:
        try:
            data = {"ticket": {"state": state}}
            if note:
                data["article"] = {"body": note, "type": "note", "internal": False}
            result = self._put(f"tickets/{ticket_id}", json=data)
            logger.info(f"✅ Статус тикета #{ticket_id} обновлён на {state}")
            return result
        except Exception as e:
            logger.error(f"❌ Ошибка обновления статуса: {e}")
            raise