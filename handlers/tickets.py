import logging
from maxapi import F
from maxapi.types import MessageCallback, MessageCreated

from services.zammad_client import ZammadClient
from utils.keyboard import get_status_buttons, get_main_keyboard, get_ticket_keyboard
from utils.formatter import format_ticket_details, format_ticket_list

logger = logging.getLogger(__name__)


def register_callback_handlers(dp, zammad: ZammadClient):
    """Регистрация обработчиков callback-кнопок"""

    # Обработка callback через message_created с фильтром
    @dp.message_created(F.message.callback.data.startswith("ticket:"))
    async def handle_ticket_callback(event: MessageCreated):
        """Обработка кнопок управления тикетом"""
        callback = event.message.callback
        data = callback.data

        # Парсим callback: ticket:123:action:extra
        parts = data.split(":")
        if len(parts) < 3:
            await event.message.answer("❌ Неверный формат запроса", show_alert=True)
            return

        ticket_id = int(parts[1])
        action = parts[2]
        extra = parts[3] if len(parts) > 3 else None

        if action == "comment":
            # Запрос комментария к тикету
            event.state.set("waiting_for_comment", comment_ticket_id=ticket_id)
            await event.message.answer(
                f"✍️ **Добавьте комментарий к заявке #{ticket_id}**\n\n"
                "Напишите сообщение или нажмите «Отмена»",
                reply_markup=get_main_keyboard(cancel=True),
                parse_mode="Markdown",
            )

        elif action == "status":
            # Показать кнопки выбора статуса
            await event.message.answer(
                f"📊 **Изменение статуса заявки #{ticket_id}**\n\n"
                "Выберите новый статус:",
                reply_markup=get_status_buttons(ticket_id),
                parse_mode="Markdown",
            )

        elif action == "state" and extra:
            # Применение статуса
            state_map = {
                "open": "open",
                "solved": "solved",
                "closed": "closed",
                "pending": "pending",
            }
            new_state = state_map.get(extra)
            if not new_state:
                await event.message.answer("❌ Неверный статус", show_alert=True)
                return

            try:
                await zammad.update_ticket_state(
                    ticket_id=ticket_id,
                    state=new_state,
                    note=f"Статус изменён через бота"
                )
                # Обновляем сообщение с новым статусом
                ticket = await zammad.get_ticket(ticket_id)
                await event.message.answer(
                    format_ticket_details(ticket),
                    reply_markup=get_ticket_keyboard(ticket_id),
                    parse_mode="Markdown",
                )
                await event.message.answer(f"✅ Статус изменён на «{new_state}»")
            except Exception as e:
                logger.error(f"Ошибка обновления статуса: {e}")
                await event.message.answer("❌ Ошибка при обновлении статуса")

        elif action == "cancel":
            # Отмена действия
            await event.message.answer(
                "✅ Действие отменено",
                reply_markup=get_main_keyboard(),
            )

        else:
            await event.message.answer("⚠️ Действие недоступно")

    @dp.message_created(F.message.callback.data == "main:new_ticket")
    async def handle_new_ticket_callback(event: MessageCreated):
        """Кнопка «Новая заявка» из главной клавиатуры"""
        event.state.set("waiting_for_ticket_text")
        await event.message.answer(
            "✍️ **Создание новой заявки**\n\n"
            "Опишите вашу проблему. Можно прикрепить файлы.",
            reply_markup=get_main_keyboard(cancel=True),
            parse_mode="Markdown",
        )

    @dp.message_created(F.message.callback.data == "main:my_tickets")
    async def handle_my_tickets_callback(event: MessageCreated):
        """Кнопка «Мои заявки» из главной клавиатуры"""
        user = event.message.sender
        email = getattr(user, 'email', None) or getattr(user, 'login', None) or f"user_{user.id}@max.local"

        await event.message.answer("🔍 Загрузка...")
        tickets = await zammad.get_user_tickets(email=email, limit=10)

        if not tickets:
            await event.message.answer(
                "📭 У вас пока нет заявок.\n/new — создать новую",
                reply_markup=get_main_keyboard(),
                parse_mode="Markdown",
            )
            return

        text = format_ticket_list(tickets)
        await event.message.answer(text, reply_markup=get_main_keyboard(), parse_mode="Markdown")