import logging
from maxapi import F
from maxapi.types import MessageCreated, Command, BotStarted  # Убрали CallbackQuery

from services.zammad_client import ZammadClient
from utils.keyboard import get_main_keyboard, get_ticket_keyboard
from utils.formatter import format_ticket_list, format_ticket_details

logger = logging.getLogger(__name__)


def register_command_handlers(dp, zammad: ZammadClient):
    """Регистрация обработчиков команд"""

    @dp.bot_started()
    async def on_start(event: BotStarted):
        """Приветствие при первом запуске"""
        await event.bot.send_message(
            chat_id=event.chat_id,
            text="👋 Добро пожаловать в бот поддержки!\n\n"
                 "Я помогу вам создать и отслеживать заявки в системе Zammad.\n\n"
                 "Доступные команды:\n"
                 "/start - Начать работу\n"
                 "/new - Создать новую заявку\n"
                 "/tickets - Мои заявки\n"
                 "/help - Помощь",
            reply_markup=get_main_keyboard(),
        )

    @dp.message_created(Command('start'))
    async def cmd_start(event: MessageCreated):
        """Обработчик /start"""
        await event.message.answer(
            "🎯 Выберите действие:",
            reply_markup=get_main_keyboard(),
        )

    @dp.message_created(Command('help'))
    async def cmd_help(event: MessageCreated):
        """Обработчик /help"""
        help_text = (
            "📚 **Справка по боту**\n\n"
            "🔹 **Создание заявки**:\n"
            "   • Нажмите /new или кнопку «Новая заявка»\n"
            "   • Опишите проблему в сообщении\n"
            "   • При необходимости прикрепите файлы\n\n"
            "🔹 **Просмотр заявок**:\n"
            "   • /tickets - список ваших заявок\n"
            "   • /ticket #123 - детали конкретной заявки\n\n"
            "🔹 **Управление**:\n"
            "   • Ответы на сообщения от поддержки придут в чат\n"
            "   • Статусы заявок обновляются автоматически\n\n"
            "💡 **Совет**: Чем подробнее описание, тем быстрее помощь!"
        )
        await event.message.answer(help_text, parse_mode="Markdown")

    @dp.message_created(Command('new'))
    async def cmd_new_ticket(event: MessageCreated):
        """Начать создание новой заявки"""
        await event.message.answer(
            "✍️ **Создание новой заявки**\n\n"
            "Опишите вашу проблему или вопрос.\n"
            "Можете прикрепить скриншоты или файлы.\n\n"
            "📝 *Напишите сообщение, и я создам заявку в системе*",
            reply_markup=get_main_keyboard(cancel=True),
        )
        # Устанавливаем состояние для ожидания текста заявки
        event.state.set("waiting_for_ticket_text")

    @dp.message_created(Command('tickets'))
    async def cmd_my_tickets(event: MessageCreated):
        """Показать список заявок пользователя"""
        user = event.message.sender
        email = getattr(user, 'email', None) or getattr(user, 'login', None) or f"user_{user.id}@max.local"

        await event.message.answer("🔍 Загружаю ваши заявки...")

        tickets = await zammad.get_user_tickets(email=email, limit=10)

        if not tickets:
            await event.message.answer(
                "📭 У вас пока нет заявок.\n"
                "Создать новую: /new",
                reply_markup=get_main_keyboard(),
            )
            return

        text = format_ticket_list(tickets)
        await event.message.answer(
            text,
            reply_markup=get_main_keyboard(),
            parse_mode="Markdown",
        )

    @dp.message_created(Command('ticket'))
    async def cmd_ticket_details(event: MessageCreated):
        """Показать детали заявки по номеру"""
        args = event.message.body.text.split()
        if len(args) < 2:
            await event.message.answer(
                "❌ Укажите номер заявки:\n"
                "Пример: `/ticket #123` или `/ticket 123`",
                parse_mode="Markdown",
            )
            return

        ticket_number = args[1].lstrip('#')

        try:
            ticket_id = int(ticket_number)
            ticket = await zammad.get_ticket(ticket_id)

            if not ticket:
                await event.message.answer(f"❌ Заявка #{ticket_number} не найдена")
                return

            text = format_ticket_details(ticket)
            await event.message.answer(
                text,
                reply_markup=get_ticket_keyboard(ticket_id),
                parse_mode="Markdown",
            )

        except ValueError:
            await event.message.answer("❌ Неверный формат номера заявки")