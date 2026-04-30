"""
Опрос Zammad API на наличие новых сообщений от операторов
Заменяет webhook если он не поддерживается
"""

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Dict, List, Any

from database.repository import get_repos
from services.zammad_client import ZammadClient
from maxapi import Bot

logger = logging.getLogger(__name__)


class ZammadPollingService:
    """Сервис опроса Zammad на новые сообщения"""

    def __init__(self, bot: Bot, zammad: ZammadClient):
        self.bot = bot
        self.zammad = zammad
        self.last_check = datetime.utcnow() - timedelta(minutes=5)
        self.processed_articles: set = set()  # Уже обработанные сообщения
        self.is_running = False

    async def start(self, interval: int = 10):
        """Запуск опроса"""
        self.is_running = True
        logger.info(f"🔄 Запуск polling сервиса (интервал: {interval}с)")

        while self.is_running:
            try:
                await self._check_new_messages()
                await asyncio.sleep(interval)
            except asyncio.CancelledError:
                logger.info("🔄 Polling сервис остановлен")
                break
            except Exception as e:
                logger.error(f"❌ Ошибка polling: {e}", exc_info=True)
                await asyncio.sleep(interval)

    async def _check_new_messages(self):
        """Проверка новых сообщений"""
        # Получаем все открытые тикеты из БД
        ticket_repo = get_repos()['ticket']
        open_tickets = ticket_repo.get_all_open_tickets(limit=100)

        logger.debug(f"🔍 Проверка {len(open_tickets)} тикетов на новые сообщения")

        for ticket in open_tickets:
            try:
                await self._check_ticket_articles(ticket)
            except Exception as e:
                logger.error(f"❌ Ошибка проверки тикета #{ticket.zammad_ticket_id}: {e}")

    async def _check_ticket_articles(self, ticket):
        """Проверка новых статей в тикете"""
        zammad_ticket_id = ticket.zammad_ticket_id

        # Получаем тикет с статьями из Zammad
        try:
            ticket_data = await self.zammad.get_ticket(zammad_ticket_id)
            if not ticket_data:
                return

            articles = ticket_data.get('articles', [])
            if not articles:
                return

            # Проверяем каждую статью
            for article in articles:
                article_id = article.get('id')

                # Пропускаем если уже обработали
                if article_id in self.processed_articles:
                    continue

                # Пропускаем если старое
                created_at = article.get('created_at')
                if created_at:
                    try:
                        article_time = datetime.fromisoformat(created_at.replace('Z', '+00:00'))
                        if article_time.replace(tzinfo=None) < self.last_check:
                            continue
                    except:
                        pass

                # Пропускаем если от клиента
                if article.get('sender') == 'Customer':
                    self.processed_articles.add(article_id)
                    continue

                # Пропускаем внутренние заметки
                if article.get('internal'):
                    self.processed_articles.add(article_id)
                    continue

                # Отправляем сообщение пользователю
                await self._send_article_to_max(ticket, article)
                self.processed_articles.add(article_id)

            # Обновляем время последней проверки для этого тикета
            ticket.last_sync_at = datetime.utcnow()

        except Exception as e:
            logger.error(f"❌ Ошибка получения тикета #{zammad_ticket_id}: {e}")

    async def _send_article_to_max(self, ticket, article: Dict[str, Any]):
        """Отправка статьи пользователю в MAX"""
        # Находим пользователя
        user_repo = get_repos()['user']
        user = user_repo.get_by_id(ticket.user_id)

        if not user:
            logger.warning(f"⚠️ Не найден пользователь для тикета #{ticket.zammad_ticket_id}")
            return

        chat_id = user.chat_id
        if not chat_id:
            logger.warning(f"⚠️ Не найден chat_id для пользователя {user.id}")
            return

        # Формируем сообщение
        sender_name = article.get('by', {}).get('name', 'Поддержка')
        subject = article.get('subject', '')
        body = article.get('body', '')

        text_parts = []
        if subject and subject.lower() != 're: ticket':
            text_parts.append(f"📌 {subject}")
        if body:
            text_parts.append(body)

        message_text = "\n\n".join(text_parts) if text_parts else "📨 Новое сообщение от поддержки"

        # Отправляем
        await self.bot.send_message(
            chat_id=chat_id,
            text=f"👨‍ **{sender_name}**:\n\n{message_text}\n\n🎫 Заявка #{ticket.zammad_ticket_number}"
        )

        logger.info(f"✅ Отправлено сообщение пользователю {user.max_user_id}")

        # Сохраняем в БД
        message_repo = get_repos()['message']
        message_repo.create_message(
            ticket_id=ticket.id,
            zammad_article_id=article.get('id'),
            sender_type='Agent',
            sender_name=sender_name,
            subject=subject,
            body=body,
            is_internal=False,
            is_sent_to_max=True,
        )

    def stop(self):
        """Остановка сервиса"""
        self.is_running = False
        logger.info("🔄 Polling сервис остановлен")


# =============================================================================
# Интеграция с main.py
# =============================================================================

async def start_polling_service(bot: Bot, zammad: ZammadClient):
    """Запуск сервиса опроса Zammad"""
    service = ZammadPollingService(bot, zammad)
    await service.start(interval=10)  # Проверка каждые 10 секунд