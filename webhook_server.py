"""
Webhook сервер для Zammad 7.0 — БЕЗ SSL
Использует очередь для отправки сообщений через главный цикл
Запуск: python webhook_server.py --port 8080
"""

import asyncio
import logging
import json
import sys
import argparse
import queue
from typing import Dict, Any, Optional
from datetime import datetime, timezone, timedelta

from aiohttp import web

try:
    from config import config
    from database.repository import init_database, get_repos
    from services.zammad_client import ZammadClient, get_user_from_cache, set_user_in_cache
    from services.chat_mapper import init_mapper, get_mapper
    from maxapi import Bot
except ImportError:
    sys.path.insert(0, '.')
    from config import config
    from database.repository import init_database, get_repos
    from services.zammad_client import ZammadClient, get_user_from_cache, set_user_in_cache
    from services.chat_mapper import init_mapper, get_mapper
    from maxapi import Bot

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("webhook.log", encoding="utf-8", mode="a")
    ]
)
logger = logging.getLogger(__name__)

from shared_state import message_queue


class ZammadWebhookHandler:
    """Обработчик webhook событий от Zammad 7.0"""

    def __init__(self, bot: Bot):
        self.bot = bot
        self.repos = get_repos()
        self.mapper = get_mapper()

    def _queue_message(self, chat_id: int, text: str):
        """Добавляет сообщение в очередь для отправки главным циклом"""
        try:
            message_queue.put({'chat_id': chat_id, 'text': text})
            logger.info(f"Сообщение добавлено в очередь: chat_id={chat_id}")
        except Exception as e:
            logger.error(f"Ошибка добавления в очередь: {e}")

    def _format_datetime_moscow(self, iso_string: str) -> str:
        """🔥 Конвертирует ISO datetime в московское время (UTC+3)"""
        if not iso_string:
            return 'Н/Д'
        try:
            dt_string = iso_string.replace('Z', '+00:00')
            dt = datetime.fromisoformat(dt_string)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            moscow_tz = timezone(timedelta(hours=3))
            dt_moscow = dt.astimezone(moscow_tz)
            return dt_moscow.strftime('%d.%m.%Y %H:%M')
        except:
            return iso_string[:16] if iso_string else 'Н/Д'

    async def handle_event(self, event_data: Dict[str, Any]) -> bool:
        """Главный обработчик события от Zammad"""
        event_type = event_data.get('event')
        ticket_id = event_data.get('ticket_id')

        if not ticket_id and 'ticket' in event_data:
            ticket = event_data.get('ticket', {})
            if isinstance(ticket, dict):
                ticket_id = ticket.get('id')

        if not event_type:
            article = event_data.get('article', {})
            if article and isinstance(article, dict) and article.get('body'):
                event_type = 'article.created'
            elif 'ticket' in event_data:
                event_type = 'ticket.updated'
            else:
                event_type = 'ticket.updated'

        if not ticket_id:
            logger.warning(f"Не удалось извлечь ticket_id: {event_data}")
            return False

        logger.info(f"Webhook: {event_type} #{ticket_id}")

        try:
            self.repos['webhook'].log_event(
                event_type=event_type,
                ticket_id=ticket_id,
                payload=event_data
            )
        except Exception as e:
            logger.debug(f"Не удалось залогировать событие: {e}")

        try:
            if event_type == 'ticket.updated' or ('ticket' in event_data and 'article' in event_data):
                return await self._handle_ticket_updated(event_data)
            elif event_type == 'article.created':
                return await self._handle_article_created(event_data)
            elif event_type == 'ticket.created':
                return await self._handle_ticket_created(event_data)
            else:
                logger.debug(f"Пропущено событие: {event_type}")
                return True
        except Exception as e:
            logger.error(f"Ошибка обработки события {event_type}: {e}", exc_info=True)
            return False

    async def _handle_ticket_updated(self, event_data: Dict[str, Any]) -> bool:
        """Обновление заявки: выводит полную информацию с эмодзи"""
        ticket = event_data.get('ticket', {})
        if not ticket:
            ticket = event_data

        ticket_id = ticket.get('id') or event_data.get('ticket_id')
        if not ticket_id:
            logger.warning(f"Нет ticket_id в событии")
            return False

        customer_id = ticket.get('customer_id')
        if not customer_id:
            logger.debug(f"Нет customer_id в тикете #{ticket_id}")
            return True

        user = self.repos['user'].get_by_zammad_id(customer_id)
        if not user:
            logger.debug(f"Пользователь не найден для customer_id={customer_id}")
            return True

        chat_id = user.get('chat_id')
        if not chat_id:
            logger.warning(f"Нет chat_id для пользователя {user.get('max_user_id')}")
            return True

        logger.info(f"Найден пользователь: max_id={user.get('max_user_id')} для тикета #{ticket_id}")

        # Формируем полную информацию о заявке с эмодзи
        title = ticket.get('title', 'Без заголовка')
        state_id = ticket.get('state_id')
        state_text = self._format_state(state_id)
        priority_id = ticket.get('priority_id')
        priority_text = self._format_priority(priority_id)

        # Исполнитель
        owner_name = await self._get_owner_name(ticket)

        # Группа
        group = ticket.get('group', 'Users')
        if isinstance(group, dict):
            group = group.get('name', 'Users')

        # 🔥 Даты - московское время (UTC+3)
        created_at = ticket.get('created_at', '')
        updated_at = ticket.get('updated_at', '')

        created_str = self._format_datetime_moscow(created_at)
        updated_str = self._format_datetime_moscow(updated_at)

        # 🔥 Формируем сообщение с эмодзи
        message_parts = [
            f"🎫 Заявка #{ticket_id}",
            "",
            f"📌 {title}",
            "",
            f"📊 Статус: {state_text}",
            f"⚡ Приоритет: {priority_text}",
            f"👤 Исполнитель: {owner_name}",
            "",
            f"🕐 Создана: {created_str}",
            f"🔄 Обновлено: {updated_str}",
        ]

        full_message = "\n".join(message_parts)

        # Отправляем сообщение
        self._queue_message(
            chat_id=chat_id,
            text=full_message
        )

        logger.info(f"Уведомление добавлено в очередь для пользователя {user.get('max_user_id')}")

        # Обновляем тикет в БД
        try:
            self.repos['ticket'].sync_ticket(
                zammad_ticket_id=ticket_id,
                zammad_ticket_number=str(ticket.get('number', ticket_id)),
                user_id=user['id'],
                state=ticket.get('state'),
                state_id=state_id,
                priority=str(ticket.get('priority_id')),
            )
        except Exception as e:
            logger.debug(f"Не удалось обновить тикет в БД: {e}")

        return True

    async def _handle_article_created(self, event_data: Dict[str, Any]) -> bool:
        """Новое сообщение в заявке (от оператора)"""
        ticket = event_data.get('ticket', {})
        if not ticket:
            ticket = event_data

        ticket_id = ticket.get('id')
        article = event_data.get('article', {})

        if not ticket_id:
            logger.debug(f"Нет ticket_id в событии article.created")
            return True

        sender = article.get('sender')
        if sender == 'Customer':
            logger.info(f"Пропущено сообщение от клиента в тикете #{ticket_id}")
            return True

        internal = article.get('internal')
        if internal:
            logger.info(f"Пропущена внутренняя заметка в тикете #{ticket_id}")
            return True

        customer_id = ticket.get('customer_id')
        if not customer_id:
            logger.debug(f"Нет customer_id в тикете #{ticket_id}")
            return True

        user = self.repos['user'].get_by_zammad_id(customer_id)
        if not user:
            logger.debug(f"Пользователь не найден для customer_id={customer_id}")
            return True

        chat_id = user.get('chat_id')
        if not chat_id:
            logger.warning(f"Нет chat_id для пользователя {user.get('max_user_id')}")
            return True

        logger.info(f"Добавляем сообщение в очередь: chat_id={chat_id}")

        sender_name = article.get('by', {}).get('name', 'Поддержка')
        if not sender_name and 'from' in article:
            sender_name = article['from'].get('name', 'Поддержка')
        if not sender_name:
            sender_name = 'Поддержка'

        subject = article.get('subject', '')
        body = article.get('body', '')

        text_parts = []
        if subject and subject.lower() != 're: ticket':
            text_parts.append(f"📌 {subject}")
        if body:
            text_parts.append(body)

        message_text = "\n\n".join(text_parts) if text_parts else "📨 Новое сообщение от поддержки"

        # Добавляем в очередь
        self._queue_message(
            chat_id=chat_id,
            text=f"👨‍💻 {sender_name}:\n\n{message_text}\n\n🎫 Заявка #{ticket_id}"
        )

        logger.info(f"Сообщение добавлено в очередь для пользователя {user.get('max_user_id')}")
        return True

    async def _handle_ticket_created(self, event_data: Dict[str, Any]) -> bool:
        """Создание заявки"""
        ticket = event_data.get('ticket', {})
        if not ticket:
            ticket = event_data

        ticket_id = ticket.get('id')
        logger.debug(f"Пропущено создание тикета #{ticket_id}")
        return True

    def _format_state(self, state_id: Any) -> str:
        """Форматирует статус заявки"""
        states = {
            1: "🆕 Новая",
            2: "🟡 В работе",
            3: "⏸️ На паузе",
            4: "🔴 Решена",
            5: "🔴 Закрыта",
        }
        try:
            state_id = int(state_id)
            return states.get(state_id, f"ID:{state_id}")
        except:
            return str(state_id)

    def _format_priority(self, priority: Any) -> str:
        """Форматирует приоритет"""
        if isinstance(priority, int):
            return {1: "🟢 Низкий", 2: "🟡 Обычный", 3: "🟠 Высокий", 4: "🔴 Критический"}.get(priority, "🟡 Обычный")
        if not priority:
            return "🟡 Обычный"
        p = str(priority).lower()
        if 'low' in p:
            return "🟢 Низкий"
        if 'normal' in p:
            return "🟡 Обычный"
        if 'high' in p:
            return "🟠 Высокий"
        if 'urgent' in p:
            return "🔴 Критический"
        return "🟡 Обычный"

    async def _get_owner_name(self, ticket: Dict) -> str:
        """Получает имя исполнителя"""
        owner_id = ticket.get('owner_id')
        if not owner_id:
            return "Не назначен"

        if 'assets' in ticket and 'User' in ticket['assets']:
            users = ticket['assets']['User']
            if isinstance(users, dict) and str(owner_id) in users:
                u = users[str(owner_id)]
                name = f"{u.get('firstname', '')} {u.get('lastname', '')}".strip()
                if name:
                    return name

        owner = ticket.get('owner')
        if isinstance(owner, dict):
            name = f"{owner.get('firstname', '')} {owner.get('lastname', '')}".strip()
            if name:
                return name
            name = owner.get('login', '')
            if name:
                return name

        info = get_user_from_cache(owner_id)
        if info:
            name = f"{info.get('firstname', '')} {info.get('lastname', '')}".strip()
            if name:
                return name
            name = info.get('login', '')
            if name:
                return name

        return f"ID: {owner_id}"


class WebhookApp:
    """Webhook приложение"""

    def __init__(self, bot: Bot):
        self.bot = bot
        self.handler = ZammadWebhookHandler(bot)

    async def handle_webhook(self, request: web.Request) -> web.Response:
        """Обработчик POST запросов от Zammad"""
        try:
            logger.info(f"POST /webhook/zammad from {request.remote}")

            try:
                body = await request.text()
                logger.debug(f"Raw body: {body[:1000]}")
                event_data = json.loads(body)
            except json.JSONDecodeError as e:
                logger.error(f"Неверный JSON: {e}")
                logger.error(f"Body: {body[:200]}")
                return web.Response(status=400, text="Invalid JSON")

            success = await self.handler.handle_event(event_data)

            if success:
                return web.Response(status=200, text="OK")
            else:
                return web.Response(status=400, text="Processing failed")

        except Exception as e:
            logger.error(f"Ошибка обработки вебхука: {e}", exc_info=True)
            return web.Response(status=500, text="Internal Error")

    async def handle_health(self, request: web.Request) -> web.Response:
        """Health check endpoint"""
        return web.json_response({
            "status": "ok",
            "service": "zammad-max-webhook",
            "timestamp": datetime.now().isoformat()
        })

    def create_app(self) -> web.Application:
        """Создание aiohttp приложения"""
        app = web.Application()

        app.router.add_post('/webhook/zammad', self.handle_webhook)
        app.router.add_get('/health', self.handle_health)
        app.router.add_get('/', self.handle_health)

        logger.info("Webhook app создан")
        return app


async def run_webhook_server(bot: Bot, host: str = '0.0.0.0', port: int = 8080):
    """Запуск webhook сервера БЕЗ SSL"""
    app = WebhookApp(bot).create_app()
    runner = web.AppRunner(app)
    await runner.setup()

    site = web.TCPSite(runner, host, port)
    await site.start()

    logger.info(f"Webhook сервер запущен: http://{host}:{port}/webhook/zammad")
    logger.info(f"Health check: http://{host}:{port}/health")

    try:
        while True:
            await asyncio.sleep(3600)
    except asyncio.CancelledError:
        logger.info("Остановка webhook сервера")
        await runner.cleanup()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description='Zammad Webhook Server (HTTP)')
    parser.add_argument('--port', type=int, default=8080, help='Port to listen on')
    parser.add_argument('--host', type=str, default='0.0.0.0', help='Host to bind')

    args = parser.parse_args()

    async def main():
        init_database("sqlite:///bot.db")
        init_mapper()

        bot = Bot(token=config.max_bot_token)

        await run_webhook_server(
            bot=bot,
            host=args.host,
            port=args.port
        )

    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("Остановлено")