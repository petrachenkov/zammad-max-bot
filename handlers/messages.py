# handlers/messages.py
import logging
from maxapi import F
from maxapi.types import MessageCreated

from services.zammad_client import ZammadClient
from utils.keyboard import get_main_keyboard, get_cancel_keyboard

logger = logging.getLogger(__name__)


def register_message_handlers(dp, zammad: ZammadClient):
    """Регистрация обработчиков текстовых сообщений"""

    @dp.message_created(F.message.body.text & F.state("waiting_for_ticket_text"))
    async def handle_ticket_text(event: MessageCreated):
        """Обработка текста для создания заявки"""
        user = event.message.sender
        text = event.message.body.text.strip()

        if text.lower() in ["отмена", "cancel", "❌"]:
            event.state.reset()
            await event.message.answer(
                "✅ Создание заявки отменено",
                reply_markup=get_main_keyboard(),
            )
            return

        if len(text) < 10:
            await event.message.answer(
                "⚠️ Пожалуйста, опишите проблему подробнее (минимум 10 символов)"
            )
            return

        email = getattr(user, 'email', None) or getattr(user, 'login', None) or f"user_{user.id}@max.local"
        name = f"{getattr(user, 'first_name', '')} {getattr(user, 'last_name', '')}".strip() or None

        try:
            await event.message.answer("⏳ Создаю заявку в системе...")

            ticket = await zammad.create_ticket(
                title=text[:100],
                body=text,
                customer_email=email,
                customer_name=name,
            )

            event.state.reset()

            await event.message.answer(
                f"✅ **Заявка создана!**\n\n"
                f"🎫 Номер: `#{ticket.get('number')}`\n"
                f"📊 Статус: {ticket.get('state', 'new')}\n"
                f"👥 Группа: {ticket.get('group', 'Users')}\n\n"
                f"Вы получите уведомление, когда появится ответ от поддержки.",
                reply_markup=get_main_keyboard(),
                parse_mode="Markdown",
            )

        except Exception as e:
            logger.error(f"Ошибка создания тикета: {e}")
            await event.message.answer(
                "❌ Произошла ошибка при создании заявки.\n"
                "Попробуйте позже или свяжитесь с администратором.",
                reply_markup=get_main_keyboard(),
            )

    @dp.message_created(F.message.body.text & F.state("waiting_for_comment"))
    async def handle_ticket_comment(event: MessageCreated):
        """Обработка комментария к заявке"""
        text = event.message.body.text.strip()

        if text.lower() in ["отмена", "cancel", "❌"]:
            event.state.reset()
            await event.message.answer("✅ Отменено", reply_markup=get_main_keyboard())
            return

        ticket_id = event.state.get("comment_ticket_id")

        try:
            await zammad.add_article(
                ticket_id=ticket_id,
                body=text,
                sender="Customer",
            )
            event.state.reset()

            await event.message.answer(
                f"✅ Комментарий добавлен к заявке #{ticket_id}",
                reply_markup=get_main_keyboard(),
            )

        except Exception as e:
            logger.error(f"Ошибка добавления комментария: {e}")
            await event.message.answer("❌ Ошибка при добавлении комментария")

    @dp.message_created(F.message.body.text & (F.message.text.contains("❌ Отмена")))
    async def handle_cancel(event: MessageCreated):
        """Обработка кнопки отмены"""
        event.state.reset()
        await event.message.answer(
            "✅ Отменено",
            reply_markup=get_main_keyboard(),
        )