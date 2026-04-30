"""
Zammad + MAX Bot — Полная версия с картриджами и удалением сообщений
🔒 Защита от SQL-инъекций + Rate Limiting + Webhook + Картриджи + Delete Message
"""

import asyncio
import logging
import re
import threading
import queue
from typing import Dict, Any, Optional, List
from datetime import datetime, timezone, timedelta

from maxapi import Bot
from maxapi.types import CallbackButton
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

from config import config
from database.repository import init_database, get_repos, sanitize_string, validate_login, validate_password
from services.zammad_client import ZammadClient, get_user_from_cache, set_user_in_cache
from services.chat_mapper import init_mapper, get_mapper
from utils.formatter import format_ticket_list, format_ticket_details

# 🔥 Картриджи
from shared_state import message_queue
from database.cartridge_models import init_cartridge_database
from database.cartridge_repository import CartridgeRepository
from services.cartridge_service import CartridgeService

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("bot.log", encoding="utf-8", mode="a")
    ]
)
logger = logging.getLogger(__name__)

# =============================================================================
# ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ
# =============================================================================

bot: Optional[Bot] = None
zammad: Optional[ZammadClient] = None
user_states: Dict[int, Dict[str, Any]] = {}

# 🔥 Хранилище последних сообщений бота по чатам (для удаления)
# Format: {chat_id: {"message_id": "12345", "text": "...", "timestamp": ...}}
bot_last_messages: Dict[int, Dict[str, Any]] = {}

# 🔥 Картриджи
cartridge_engine = None
cartridge_session = None
cartridge_repo: Optional[CartridgeRepository] = None
cartridge_service: Optional[CartridgeService] = None
cartridge_user_states: Dict[int, Dict[str, Any]] = {}

# =============================================================================
# 🔒 БЕЗОПАСНОСТЬ — Rate Limiting
# =============================================================================

auth_attempts: Dict[int, List[datetime]] = {}
AUTH_LIMIT = 5
AUTH_WINDOW = 300


def check_auth_rate_limit(user_id: int) -> bool:
    now = datetime.utcnow()
    if user_id not in auth_attempts:
        auth_attempts[user_id] = []
    auth_attempts[user_id] = [
        t for t in auth_attempts[user_id]
        if now - t < timedelta(seconds=AUTH_WINDOW)
    ]
    if len(auth_attempts[user_id]) >= AUTH_LIMIT:
        logger.warning(f"🔒 Rate limit превышен для пользователя {user_id}")
        return False
    return True


def record_auth_attempt(user_id: int):
    if user_id not in auth_attempts:
        auth_attempts[user_id] = []
    auth_attempts[user_id].append(datetime.utcnow())


def clear_auth_attempts(user_id: int):
    if user_id in auth_attempts:
        del auth_attempts[user_id]


# =============================================================================
# УТИЛИТЫ
# =============================================================================

def get_user_state(user_id: int) -> Dict[str, Any]:
    if user_id not in user_states:
        user_states[user_id] = {}
    return user_states[user_id]


def set_user_state(user_id: int, **kwargs):
    if user_id not in user_states:
        user_states[user_id] = {}
    user_states[user_id].update(kwargs)


def reset_user_state(user_id: int):
    if user_id in user_states:
        user_states[user_id] = {}


def create_main_keyboard() -> list:
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="🟡 Открытые", payload="cmd:open"),
        CallbackButton(text="🔴 Закрытые", payload="cmd:closed"),
    )
    builder.row(
        CallbackButton(text="📋 Все заявки", payload="cmd:tickets"),
        CallbackButton(text="✍️ Создать", payload="cmd:new"),
    )
    builder.row(
        CallbackButton(text="👤 Профиль", payload="cmd:profile"),
        CallbackButton(text="🔐 Выйти", payload="cmd:logout"),
    )
    # 🔥 Кнопка для картриджей
    builder.row(
        CallbackButton(text="🖨️ Заправка картриджей", payload="cmd:cartridge"),
    )
    return [builder.as_markup()]


def create_auth_keyboard() -> list:
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="🔐 Войти", payload="cmd:login_prompt"),
        CallbackButton(text="❓ Помощь", payload="cmd:help"),
    )
    return [builder.as_markup()]


def create_cancel_keyboard() -> list:
    builder = InlineKeyboardBuilder()
    builder.row(CallbackButton(text="❌ Отмена", payload="cmd:cancel"))
    return [builder.as_markup()]


def create_ticket_keyboard(ticket_id: int) -> list:
    builder = InlineKeyboardBuilder()
    builder.row(
        CallbackButton(text="📝 Комментарий", payload=f"act:comment:{ticket_id}"),
        CallbackButton(text="🔄 Обновить", payload=f"act:refresh:{ticket_id}"),
    )
    builder.row(
        CallbackButton(text="🔴 Закрыть", payload=f"act:close:{ticket_id}"),
        CallbackButton(text="⬅️ Назад", payload="cmd:tickets"),
    )
    return [builder.as_markup()]


async def send_text(
    chat_id: int,
    text: str,
    keyboard: Optional[list] = None,
    delete_before: bool = False,
    store_message: bool = True
):
    """
    Отправка текста с опцией удаления предыдущего сообщения

    🔥 Параметры:
    - delete_before=True: удаляет сообщение ПЕРЕД отправкой нового
    - store_message=True: сохраняет ID сообщения для будущего удаления
    """
    # 🔥 Сначала удаляем старое сообщение (если нужно)
    if delete_before and chat_id in bot_last_messages:
        old_msg = bot_last_messages[chat_id]
        if old_msg.get('message_id'):
            try:
                await bot.delete_message(
                    chat_id=chat_id,
                    message_id=str(old_msg['message_id'])  # 🔥 message_id должен быть строкой!
                )
                logger.debug(f"🗑️ Удалено сообщение {old_msg['message_id']} в чате {chat_id}")
            except Exception as e:
                logger.debug(f"⚠️ Не удалось удалить сообщение: {e}")

    # Формируем параметры отправки
    params = {"chat_id": chat_id, "text": text}
    if keyboard:
        params["attachments"] = keyboard

    try:
        # Отправляем сообщение
        result = await bot.send_message(**params)

        # 🔥 Сохраняем информацию о новом сообщении
        if store_message and result and isinstance(result, dict):
            msg_id = result.get('message_id')
            if msg_id:
                bot_last_messages[chat_id] = {
                    'message_id': msg_id,
                    'text': text[:100],
                    'timestamp': datetime.utcnow(),
                }
                logger.debug(f"💾 Сохранено сообщение {msg_id} в чате {chat_id}")

        return result
    except Exception as e:
        logger.error(f"❌ Ошибка отправки: {e}")
        return None


async def delete_last_bot_message(chat_id: int):
    """Удалить последнее сообщение бота в чате"""
    if chat_id in bot_last_messages:
        old_msg = bot_last_messages[chat_id]
        if old_msg.get('message_id'):
            try:
                await bot.delete_message(
                    chat_id=chat_id,
                    message_id=str(old_msg['message_id'])
                )
                logger.debug(f"🗑️ Удалено сообщение {old_msg['message_id']} в чате {chat_id}")
                return True
            except Exception as e:
                logger.debug(f"⚠️ Не удалось удалить сообщение: {e}")
    return False


async def delete_user_message(chat_id: int, message_id: Optional[int] = None):
    try:
        if message_id:
            await bot.delete_message(chat_id=chat_id, message_id=str(message_id))
            logger.debug(f"🗑️ Удалено сообщение пользователя {message_id}")
    except Exception as e:
        logger.debug(f"⚠️ Не удалось удалить сообщение пользователя: {e}")


def format_name(first_name: str, last_name: str) -> str:
    name_parts = []
    if first_name:
        name_parts.append(first_name)
    if last_name:
        name_parts.append(last_name)
    return " ".join(name_parts) if name_parts else "Пользователь"


def format_datetime_moscow(iso_string: str) -> str:
    if not iso_string:
        return "Н/Д"
    try:
        dt_string = iso_string.replace('Z', '+00:00')
        dt = datetime.fromisoformat(dt_string)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        moscow_tz = timezone(timedelta(hours=3))
        dt_moscow = dt.astimezone(moscow_tz)
        return dt_moscow.strftime("%d.%m.%Y %H:%M")
    except Exception as e:
        logger.debug(f"⚠️ Ошибка форматирования даты: {e}")
        return iso_string[:16] if iso_string else "Н/Д"


def format_priority(priority: Any) -> str:
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


async def get_zammad_user_info(user_id: int) -> Optional[Dict[str, str]]:
    cached = get_user_from_cache(user_id)
    if cached:
        return cached
    try:
        user_data = await zammad.get_user(user_id)
        if user_data:
            user_info = {
                'firstname': user_data.get('firstname', ''),
                'lastname': user_data.get('lastname', ''),
                'login': user_data.get('login', ''),
            }
            set_user_in_cache(user_id, user_info)
            logger.debug(f"✅ Получены данные пользователя {user_id}: {user_info}")
            return user_info
    except Exception as e:
        logger.debug(f"⚠️ Не удалось получить пользователя {user_id}: {e}")
    return None


async def get_owner_name(ticket: Dict) -> str:
    owner_id = ticket.get('owner_id')
    if not owner_id:
        return "Не назначен"

    if 'assets' in ticket and 'User' in ticket['assets']:
        users = ticket['assets']['User']
        if isinstance(users, dict) and str(owner_id) in users:
            user_data = users[str(owner_id)]
            owner_name = f"{user_data.get('firstname', '')} {user_data.get('lastname', '')}".strip()
            if owner_name:
                return owner_name

    owner = ticket.get('owner')
    if isinstance(owner, dict):
        owner_name = f"{owner.get('firstname', '')} {owner.get('lastname', '')}".strip()
        if owner_name:
            return owner_name
        owner_name = owner.get('login', '')
        if owner_name:
            return owner_name

    if owner_id > 0:
        cached = get_user_from_cache(owner_id)
        if cached:
            owner_name = f"{cached.get('firstname', '')} {cached.get('lastname', '')}".strip()
            if owner_name:
                return owner_name
            owner_name = cached.get('login', '')
            if owner_name:
                return owner_name

        user_info = await get_zammad_user_info(owner_id)
        if user_info:
            owner_name = f"{user_info.get('firstname', '')} {user_info.get('lastname', '')}".strip()
            if owner_name:
                return owner_name
            owner_name = user_info.get('login', '')
            if owner_name:
                return owner_name

        return f"ID: {owner_id}"

    return "Не назначен"


# =============================================================================
# ОБРАБОТКА CALLBACK
# =============================================================================

def parse_callback_payload(payload: str) -> tuple:
    if not payload:
        return None, None, None
    parts = payload.split(":")
    return parts[0], parts[1] if len(parts) >= 2 else None, parts[2] if len(parts) >= 3 else None


async def handle_callback_action(chat_id: int, user_id: int, cb_type: str, action: str, param: Optional[str]):
    mapper = get_mapper()

    if cb_type == "cmd":
        if action in ["open", "открытые"]:
            if not mapper.is_authenticated(user_id):
                await send_text(chat_id, "❌ Сначала авторизуйтесь\n\n ⚠️ Если у вас нет аккаунта или вы забыли данные от него, то обратитесь к системному администратору!", create_auth_keyboard(), delete_before=True)
                return
            await handle_open_tickets(chat_id, user_id)
        elif action == "closed":
            if not mapper.is_authenticated(user_id):
                await send_text(chat_id, "❌ Сначала авторизуйтесь\n\n ⚠️ Если у вас нет аккаунта или вы забыли данные от него, то обратитесь к системному администратору!", create_auth_keyboard(), delete_before=True)
                return
            await handle_closed_tickets(chat_id, user_id)
        elif action in ["tickets", "все", "заявки"]:
            if not mapper.is_authenticated(user_id):
                await send_text(chat_id, "❌ Сначала авторизуйтесь\n\n ⚠️ Если у вас нет аккаунта или вы забыли данные от него, то обратитесь к системному администратору!", create_auth_keyboard(), delete_before=True)
                return
            await handle_my_tickets(chat_id, user_id)
        elif action == "new":
            if not mapper.is_authenticated(user_id):
                await send_text(chat_id, "❌ Сначала авторизуйтесь\n\n ⚠️ Если у вас нет аккаунта или вы забыли данные от него, то обратитесь к системному администратору!", create_auth_keyboard(), delete_before=True)
                return
            await handle_new_ticket(chat_id, user_id)
        elif action == "logout":
            await handle_logout(chat_id, user_id)
        elif action == "cancel":
            reset_user_state(user_id)
            cartridge_user_states.pop(user_id, None)
            await handle_start(chat_id, user_id, sender={})
        elif action == "help":
            text = (
                "📚 Справка\n\n"
                "❓ КАК ВОЙТИ В АККАУНТ:\n\n"
                "1. Введите логин, который используете для входа в Windows (только маленькими буквами)\n"
                "2. Введите от аккаунта пароль\n\n"
                "⚠️ Если у вас нет аккаунта или вы забыли данные от него, то обратитесь к системному администратору!\n\n"
                "🎫 КАК СОЗДАТЬ ЗАЯВКУ В ПОДДЕРЖКУ:\n\n"
                "1. Нажмите кнопку ✍️ Создать\n"
                "2. Опишите вашу проблему\n"
                "3. Бот создаст заявку и пришлёт номер\n\n"
                "📋 ЧТО МОЖНО УКАЗАТЬ В ЗАЯВКЕ:\n"
                "• Описание проблемы и кабинет\n"
                "• Фотографии и файлы бот пока не принимает\n\n"
                "🖨️ КАК ЗАКАЗАТЬ ЗАПРАВКУ КАРТРИДЖА:\n\n"
                "1. Нажмите кнопку 🖨️ Заправка картриджей\n"
                "2. Введите номер вашего кабинета\n"
                "3. Бот пришлёт код из 6 цифр\n"
                "4. Напишите код на бумажке\n"
                "5. Приклейте бумажку к картриджу\n"
                "6. Сотрудник заберёт его\n\n"
            )
            await send_text(chat_id, text, create_main_keyboard(), delete_before=True)
        elif action == "login_prompt":
            text = (
                "🔐 Авторизация\n\n"
                "Введите ваш логин от учетной записи:"
            )
            set_user_state(user_id, waiting_for="login_username")
            await send_text(chat_id, text, create_cancel_keyboard(), delete_before=True)
        elif action == "profile":
            user = mapper.get_user(user_id)
            if user:
                full_name = format_name(user.get('first_name', ''), user.get('last_name', ''))
                text = (
                    f"👤 Профиль\n\n"
                    f"Логин: {user.get('zammad_login')}\n"
                    f"Имя: {full_name}\n"
                    f"Zammad ID: {user.get('zammad_user_id')}\n"
                    f"MAX ID: {user.get('max_user_id')}\n"
                )
                await send_text(chat_id, text, create_main_keyboard(), delete_before=True)
        elif action == "start":
            await handle_start(chat_id, user_id, sender={})
        # 🔥 Картриджи
        elif action == "cartridge":
            await handle_cartridge_request(chat_id, user_id, sender={})

    # 🔥 Админские команды для картриджей (только в специальном чате)
    elif cb_type == "crt":
        if chat_id != config.cartridge_chat_id:
            await send_text(chat_id, "❌ Доступ запрещён", delete_before=True)
            return

        if action in ['received', 'cancel'] and param:
            await handle_cartridge_callback(chat_id, user_id, action, param)
        elif action in ['list_pending', 'generate_excel', 'list_reports', 'help']:
            await handle_cartridge_admin_command(chat_id, user_id, action)

    elif cb_type == "act":
        if not mapper.is_authenticated(user_id):
            await send_text(chat_id, "❌ Сначала авторизуйтесь", create_auth_keyboard(), delete_before=True)
            return
        if action == "refresh" and param:
            await handle_ticket_details(chat_id, user_id, int(param))
        elif action == "comment" and param:
            set_user_state(user_id, waiting_for="comment", ticket_id=int(param))
            text = (
                "✍️ Комментарий\n\n"
                "Напишите текст комментария:"
            )
            await send_text(chat_id, text, create_cancel_keyboard(), delete_before=True)
        elif action == "close" and param:
            set_user_state(user_id, waiting_for="confirm_close", ticket_id=int(param))
            text = (
                f"⚠️ Закрытие заявки\n\n"
                f"Вы уверены что хотите закрыть заявку #{param}?\n\n"
                "Напишите: да или нет"
            )
            await send_text(chat_id, text, create_cancel_keyboard(), delete_before=True)
        elif action == "back":
            await handle_my_tickets(chat_id, user_id)


async def process_callback(chat_id: int, user_id: int, callback_data: Dict):
    payload = callback_data.get("payload") or callback_data.get("data")
    if not payload and "callback" in callback_data:
        cb = callback_data["callback"]
        payload = cb.get("payload") or cb.get("data")
    if not payload:
        await send_text(chat_id, "❌ Ошибка кнопки", create_main_keyboard(), delete_before=True)
        return
    cb_type, action, param = parse_callback_payload(payload)
    if cb_type and action:
        await handle_callback_action(chat_id, user_id, cb_type, action, param)
    else:
        await handle_command(chat_id, user_id, {}, f"/{payload}")


# =============================================================================
# 🔥 ОБРАБОТЧИКИ КАРТРИДЖЕЙ
# =============================================================================

async def handle_cartridge_request(chat_id: int, user_id: int, sender: Dict):
    """Начало заявки на заправку картриджа"""
    mapper = get_mapper()
    if not mapper.is_authenticated(user_id):
        await send_text(chat_id, "❌ Сначала авторизуйтесь\n\n ⚠️ Если у вас нет аккаунта или вы забыли данные от него, то обратитесь к системному администратору!", create_auth_keyboard(), delete_before=True)
        return

    user = mapper.get_user(user_id)
    fio = format_name(user.get('first_name', ''), user.get('last_name', ''))

    cartridge_user_states[user_id] = {
        'waiting_for': 'cabinet',
        'fio': fio,
        'chat_id': chat_id,
    }

    text = (
        "🖨️ Заправка картриджа\n\n"
        "Введите номер вашего кабинета:"
    )
    await send_text(chat_id, text, create_cancel_keyboard(), delete_before=True)


async def handle_cartridge_cabinet(
    chat_id: int,
    user_id: int,
    cabinet: str,
    message_id: Optional[int] = None
):
    """Обработка ввода номера кабинета"""
    state = cartridge_user_states.get(user_id, {})

    if state.get('waiting_for') != 'cabinet':
        await send_text(chat_id, "❌ Ошибка: начните заявку заново", create_main_keyboard(), delete_before=True)
        return

    cabinet = cabinet.strip()
    if not cabinet or len(cabinet) > 30:
        await send_text(chat_id, "❌ Неверный номер кабинета", create_cancel_keyboard(), delete_before=True)
        return

    fio = state.get('fio', 'Пользователь')
    cartridge_id = cartridge_repo.generate_unique_cartridge_id()

    if cartridge_service:
        await cartridge_service.process_new_request(
            cartridge_id=cartridge_id,
            max_user_id=user_id,
            chat_id=chat_id,
            fio=fio,
            cabinet=cabinet,
            bot=bot,
        )

    cartridge_user_states.pop(user_id, None)

    if message_id:
        await delete_user_message(chat_id, message_id)


async def handle_cartridge_callback(
    chat_id: int,
    user_id: int,
    action: str,
    cartridge_id: str
):
    """Обработка кнопок в заявке на картридж (в админ-чате)"""
    if not config.cartridge_chat_id or int(chat_id) != int(config.cartridge_chat_id):
        await send_text(chat_id, "❌ Доступ запрещён", delete_before=True)
        return

    if not cartridge_service:
        await send_text(chat_id, "❌ Сервис картриджей не инициализирован", delete_before=True)
        return

    if action == 'received':
        success = await cartridge_service.process_received(cartridge_id, user_id, bot)
        if success:
            await send_text(chat_id, f"✅ Картридж {cartridge_id} принят", delete_before=True)
    elif action == 'cancel':
        success = await cartridge_service.process_cancel(cartridge_id, bot)
        if success:
            await send_text(chat_id, f"❌ Заявка {cartridge_id} отменена", delete_before=True)


async def handle_cartridge_admin_command(
    chat_id: int,
    user_id: int,
    command: str,
    param: Optional[str] = None
):
    """Обработка команд админа в специальном чате"""
    if not config.cartridge_chat_id or int(chat_id) != int(config.cartridge_chat_id):
        await send_text(chat_id, "❌ Доступ запрещён", delete_before=True)
        return

    if not cartridge_service:
        await send_text(chat_id, "❌ Сервис картриджей не инициализирован", delete_before=True)
        return

    if command == 'list_pending':
        requests = cartridge_repo.get_pending_requests()
        received = cartridge_repo.get_received_requests()

        if not requests and not received:
            await send_text(chat_id, "📋 Нет ожидающих заявок.", delete_before=True)
        else:
            text = "📋 Ожидающие заявки\n\n"

            if received:
                text += f"Готовы к отчёту ({len(received)}):\n"
                for r in received:
                    text += f"- {r['cartridge_id']} — {r['fio']}, каб.{r['cabinet']}\n"
                text += "\n"

            if requests:
                text += f"Ожидают получения ({len(requests)}):\n"
                for r in requests:
                    text += f"- {r['cartridge_id']} — {r['fio']}, каб.{r['cabinet']}\n"

            await send_text(chat_id, text, delete_before=True)

    elif command == 'generate_excel':
        report = await cartridge_service.generate_excel_report(
            admin_id=user_id,
            bot=bot,
            output_dir=config.cartridge_reports_dir
        )
        if report:
            await send_text(chat_id, f"✅ Отчёт сгенерирован: {report['report_name']}", delete_before=True)

    elif command == 'list_reports':
        text = await cartridge_service.list_reports(user_id, bot)
        await send_text(chat_id, text, delete_before=True)

    elif command == 'report' and param:
        try:
            index = int(param)
            success = await cartridge_service.send_report_by_index(index, user_id, bot)
            if not success:
                await send_text(chat_id, "❌ Не удалось отправить отчёт", delete_before=True)
        except ValueError:
            await send_text(chat_id, "❌ Используйте: /report <номер>", delete_before=True)

    elif command == 'help':
        await cartridge_service.show_help(bot)


# =============================================================================
# АВТОРИЗАЦИЯ И КОМАНДЫ
# =============================================================================

async def complete_login(chat_id: int, user_id: int, sender: Dict, login: str, password: str, message_id: Optional[int] = None):
    if not check_auth_rate_limit(user_id):
        text = (
            "🔒 Слишком много попыток входа\n\n"
            "Подождите 5 минут и попробуйте снова."
        )
        await send_text(chat_id, text, create_auth_keyboard(), delete_before=True)
        return

    if not validate_login(login):
        text = (
            "❌ Неверный формат логина\n\n"
            "Логин должен содержать только буквы, цифры, точку, @ или -"
        )
        await send_text(chat_id, text, create_auth_keyboard(), delete_before=True)
        return

    if not validate_password(password):
        text = (
            "❌ Неверный формат пароля\n\n"
            "Пароль должен быть минимум 4 символа"
        )
        await send_text(chat_id, text, create_auth_keyboard(), delete_before=True)
        return

    record_auth_attempt(user_id)
    await send_text(chat_id, "⏳ Проверяю учётные данные...", delete_before=True)

    user_info = await zammad.authenticate_user(login, password)
    if not user_info:
        text = (
            "❌ Ошибка\n\n"
            "Неверный логин или пароль.\n\n"
            "Попробуйте ещё раз: /login логин пароль"
        )
        await send_text(chat_id, text, create_auth_keyboard(), delete_before=True)
        reset_user_state(user_id)
        return

    clear_auth_attempts(user_id)

    user_repo = get_repos()['user']
    user_data = user_repo.create_or_update_user(
        max_user_id=user_id,
        chat_id=sender.get("chat_id", chat_id),
        zammad_user_id=user_info['id'],
        zammad_login=user_info['login'],
        first_name=user_info.get('firstname', ''),
        last_name=user_info.get('lastname', ''),
        is_authenticated=True,
    )

    mapper = get_mapper()
    check = mapper.is_authenticated(user_id)
    full_name = format_name(user_data.get('first_name', ''), user_data.get('last_name', ''))

    if message_id:
        await delete_user_message(chat_id, message_id)
    await delete_last_bot_message(chat_id)

    if check:
        text = (
            "✅ Авторизация успешна!\n\n"
            f"Пользователь: {full_name}\n"
            f"Логин: {user_data['zammad_login']}\n"
            f"Email: {user_info.get('email', 'Н/Д')}\n"
            f"Zammad ID: {user_data['zammad_user_id']}\n"
            f"MAX ID: {user_data['max_user_id']}\n\n"
            "Теперь доступны все ваши заявки."
        )
        await send_text(chat_id, text, create_main_keyboard(), delete_before=False)
    else:
        text = (
            "⚠️ Ошибка БД\n\n"
            "Попробуйте /start"
        )
        await send_text(chat_id, text, create_auth_keyboard(), delete_before=True)

    reset_user_state(user_id)


async def handle_login(chat_id: int, user_id: int, sender: Dict, credentials: str):
    parts = credentials.strip().split(maxsplit=1)
    if len(parts) != 2:
        text = (
            "❌ Ошибка\n\n"
            "Используйте: /login логин пароль"
        )
        await send_text(chat_id, text, create_auth_keyboard(), delete_before=True)
        return
    login, password = parts
    await complete_login(chat_id, user_id, sender, login, password)


async def handle_logout(chat_id: int, user_id: int):
    get_repos()['user'].logout(user_id)
    reset_user_state(user_id)
    cartridge_user_states.pop(user_id, None)
    text = (
        "✅ Выход\n\n"
        "Вы вышли из аккаунта."
    )
    await send_text(chat_id, text, create_auth_keyboard(), delete_before=True)


async def handle_start(chat_id: int, user_id: int, sender: Dict):
    mapper = get_mapper()
    if mapper.is_authenticated(user_id):
        user = mapper.get_user(user_id)
        full_name = format_name(user.get('first_name', ''), user.get('last_name', ''))
        text = (
            f"👋 С возвращением, {full_name}!\n\n"
            "Выберите действие:"
        )
        await send_text(chat_id, text, create_main_keyboard(), delete_before=True)
    else:
        text = (
            "👋 Добро пожаловать!\n\n"
            "Для доступа к заявкам:\n\n"
            "• Нажмите Войти\n"
            "• Или введите: /login логин пароль\n\n"
            "⚠️ Если у вас нет аккаунта или вы забыли данные от него, то обратитесь к системному администратору!"
        )
        await send_text(chat_id, text, create_auth_keyboard(), delete_before=True)


async def handle_bot_started(chat_id: int, user_id: int, sender: Dict):
    """Обработка BotStarted события"""
    logger.info(f"🤖 BotStarted: user_id={user_id}, chat_id={chat_id}")

    # 🔥 Очищаем состояние
    reset_user_state(user_id)
    cartridge_user_states.pop(user_id, None)

    # 🔥 Вызываем handle_start с теми же параметрами
    await handle_start(chat_id, user_id, sender)


async def handle_my_tickets(chat_id: int, user_id: int):
    mapper = get_mapper()
    if not mapper.is_authenticated(user_id):
        await send_text(chat_id, "❌ Сначала авторизуйтесь", create_auth_keyboard(), delete_before=True)
        return

    zammad_user_id = mapper.get_zammad_user_id(user_id)
    if not zammad_user_id:
        await send_text(chat_id, "❌ Ошибка: не найден Zammad user_id", create_auth_keyboard(), delete_before=True)
        return

    await send_text(chat_id, "⏳ Загружаю заявки...", delete_before=True)
    all_tickets = await zammad.get_user_tickets(zammad_user_id, limit=50)

    if not all_tickets:
        text = "📭 Нет заявок\n\nУ вас нет заявок."
    else:
        text = "📋 Все заявки:\n\n"
        for t in all_tickets[:10]:
            state_id = t.get('state_id')
            state_icon = "🆕" if state_id == 1 else "🟡" if state_id == 2 else "🔴" if state_id == 4 else "❓"
            state_name = "Новая" if state_id == 1 else "В работе" if state_id == 2 else "Закрыта" if state_id == 4 else str(state_id)
            title = t.get('title', 'Без заголовка')[:40]
            created = format_datetime_moscow(t.get('created_at', ''))
            owner_name = await get_owner_name(t)
            priority_id = t.get('priority_id') or t.get('priority')
            priority = format_priority(priority_id)

            text += f"{state_icon} #{t.get('id')} | {title}\n"
            text += f"   Статус: {state_name} | ⚡ {priority}\n"
            text += f"   👤 Исполнитель: {owner_name}\n"
            text += f"   🕐 {created}\n\n"
            mapper.sync_tickets(user_id, [t])

    await send_text(chat_id, text, create_main_keyboard(), delete_before=True)


async def handle_open_tickets(chat_id: int, user_id: int):
    mapper = get_mapper()
    if not mapper.is_authenticated(user_id):
        await send_text(chat_id, "❌ Сначала авторизуйтесь", create_auth_keyboard(), delete_before=True)
        return

    zammad_user_id = mapper.get_zammad_user_id(user_id)
    if not zammad_user_id:
        await send_text(chat_id, "❌ Ошибка: не найден Zammad user_id", create_auth_keyboard(), delete_before=True)
        return

    await send_text(chat_id, "⏳ Загружаю открытые заявки...", delete_before=True)
    all_tickets = await zammad.get_user_tickets(zammad_user_id, limit=50)
    open_tickets = [t for t in all_tickets if t.get('state_id') in [1, 2]]

    if not open_tickets:
        text = "🟡 Нет открытых заявок\n\nВсе заявки закрыты или решены!"
    else:
        text = "🟡 Открытые заявки (новые + в работе):\n\n"
        for t in open_tickets:
            state_id = t.get('state_id')
            state_icon = "🆕" if state_id == 1 else "🟡"
            state_name = "Новая" if state_id == 1 else "В работе"
            title = t.get('title', 'Без заголовка')[:40]
            created = format_datetime_moscow(t.get('created_at', ''))
            priority_id = t.get('priority_id') or t.get('priority')
            priority = format_priority(priority_id)
            owner_name = await get_owner_name(t)

            text += f"{state_icon} #{t.get('id')} | {title}\n"
            text += f"   Статус: {state_name} | ⚡ {priority}\n"
            text += f"   👤 Исполнитель: {owner_name}\n"
            text += f"   🕐 Создана: {created}\n\n"
            mapper.sync_tickets(user_id, [t])

    await send_text(chat_id, text, create_main_keyboard(), delete_before=True)


async def handle_closed_tickets(chat_id: int, user_id: int):
    mapper = get_mapper()
    if not mapper.is_authenticated(user_id):
        await send_text(chat_id, "❌ Сначала авторизуйтесь", create_auth_keyboard(), delete_before=True)
        return

    zammad_user_id = mapper.get_zammad_user_id(user_id)
    if not zammad_user_id:
        await send_text(chat_id, "❌ Ошибка: не найден Zammad user_id", create_auth_keyboard(), delete_before=True)
        return

    await send_text(chat_id, "⏳ Загружаю закрытые заявки...", delete_before=True)
    all_tickets = await zammad.get_user_tickets(zammad_user_id, limit=50)
    closed_tickets = [t for t in all_tickets if t.get('state_id') == 4]

    if not closed_tickets:
        text = "🔴 Нет закрытых заявок"
    else:
        text = "🔴 Закрытые заявки:\n\n"
        for t in closed_tickets[:10]:
            title = t.get('title', 'Без заголовка')[:40]
            created = format_datetime_moscow(t.get('created_at', ''))
            updated = format_datetime_moscow(t.get('updated_at', ''))
            owner_name = await get_owner_name(t)

            text += f"🔴 #{t.get('id')} | {title}\n"
            text += f"   👤 Исполнитель: {owner_name}\n"
            text += f"   🕐 Создана: {created} | Обновлено: {updated}\n\n"
            mapper.sync_tickets(user_id, [t])

    await send_text(chat_id, text, create_main_keyboard(), delete_before=True)


async def handle_ticket_details(chat_id: int, user_id: int, short_id: int):
    mapper = get_mapper()
    if not mapper.is_authenticated(user_id):
        await send_text(chat_id, "❌ Сначала авторизуйтесь", create_auth_keyboard(), delete_before=True)
        return

    ticket = await zammad.get_ticket(short_id)

    if ticket and ticket.get('customer_id') == mapper.get_zammad_user_id(user_id):
        state_id = ticket.get('state_id')
        state_icon = "🆕" if state_id == 1 else "🟡" if state_id == 2 else "🔴" if state_id == 4 else "❓"
        state_name = "Новая" if state_id == 1 else "В работе" if state_id == 2 else "Закрыта" if state_id == 4 else str(state_id)
        created = format_datetime_moscow(ticket.get('created_at', ''))
        updated = format_datetime_moscow(ticket.get('updated_at', ''))
        owner_name = await get_owner_name(ticket)
        priority_id = ticket.get('priority_id') or ticket.get('priority')
        priority = format_priority(priority_id)

        text = (
            f"🎫 Заявка #{ticket.get('id')}\n\n"
            f"📌 {ticket.get('title', 'Без заголовка')}\n\n"
            f"📊 Статус: {state_icon} {state_name}\n"
            f"⚡ Приоритет: {priority}\n"
            f"👤 Исполнитель: {owner_name}\n\n"
            f"🕐 Создана: {created}\n"
            f"🔄 Обновлено: {updated}\n"
        )

        mapper.sync_tickets(user_id, [ticket])
        keyboard = create_ticket_keyboard(short_id)
        await send_text(chat_id, text, keyboard, delete_before=True)
    else:
        text = (
            "❌ Не найдено\n\n"
            f"Заявка #{short_id} не найдена."
        )
        await send_text(chat_id, text, create_main_keyboard(), delete_before=True)


async def handle_new_ticket(chat_id: int, user_id: int):
    mapper = get_mapper()
    if not mapper.is_authenticated(user_id):
        await send_text(chat_id, "❌ Сначала авторизуйтесь", create_auth_keyboard(), delete_before=True)
        return
    set_user_state(user_id, waiting_for="ticket_text")
    text = (
        "✍️ Создание заявки\n\n"
        "Опишите вашу проблему или вопрос.\n\n"
        "⚠️Обязательно укажите кабинет!"
    )
    await send_text(chat_id, text, create_cancel_keyboard(), delete_before=True)


async def create_ticket_from_message(chat_id: int, user_id: int, text: str, message_id: Optional[int] = None):
    mapper = get_mapper()
    zammad_user_id = mapper.get_zammad_user_id(user_id)
    if len(text.strip()) < 10:
        await send_text(chat_id, "⚠️ Минимум 10 символов", create_cancel_keyboard(), delete_before=True)
        return

    await send_text(chat_id, "⏳ Создаю заявку...", delete_before=True)

    try:
        ticket = await zammad.create_ticket(title=text[:100], body=text, customer_id=zammad_user_id)
        mapper.sync_tickets(user_id, [ticket])
        reset_user_state(user_id)

        created = format_datetime_moscow(ticket.get('created_at', ''))
        priority_id = ticket.get('priority_id') or ticket.get('priority')
        priority = format_priority(priority_id)

        text = (
            "✅ Заявка создана!\n\n"
            f"🎫 Номер: #{ticket.get('id')}\n"
            f"📊 Статус: Новая\n"
            f"⚡ Приоритет: {priority}\n"
            f"🕐 Создана: {created}\n\n"
            f"/ticket #{ticket.get('id')} — Детали заявки"
        )
        await send_text(chat_id, text, create_main_keyboard(), delete_before=True)
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")
        await send_text(chat_id, "❌ Ошибка при создании", create_main_keyboard(), delete_before=True)


async def add_comment_to_ticket(chat_id: int, user_id: int, ticket_id: int, text: str):
    try:
        await zammad.add_article(ticket_id=ticket_id, body=text, sender="Customer")
        reset_user_state(user_id)
        text = (
            "✅ Комментарий добавлен\n\n"
            f"Сообщение добавлено к заявке #{ticket_id}."
        )
        await send_text(chat_id, text, create_main_keyboard(), delete_before=True)
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")


async def close_ticket(chat_id: int, user_id: int, ticket_id: int):
    try:
        await zammad.update_ticket_state(ticket_id, "closed")
        text = (
            "✅ Заявка закрыта\n\n"
            f"Заявка #{ticket_id} успешно закрыта."
        )
        await send_text(chat_id, text, create_main_keyboard(), delete_before=True)
    except Exception as e:
        logger.error(f"❌ Ошибка: {e}")


async def handle_command(chat_id: int, user_id: int, sender: Dict, text: str):
    parts = text.strip().split()
    cmd = parts[0].lower().lstrip("/")

    # 🔥 Команды админа для картриджей (только в специальном чате)
    if config.cartridge_chat_id and int(chat_id) == int(config.cartridge_chat_id):
        if cmd in ['list_pending', 'generate_excel', 'list_reports', 'help']:
            await handle_cartridge_admin_command(chat_id, user_id, cmd, parts[1] if len(parts) > 1 else None)
            return
        elif cmd == 'report' and len(parts) > 1:
            await handle_cartridge_admin_command(chat_id, user_id, 'report', parts[1])
            return

    if cmd == "login" and len(parts) >= 3:
        await handle_login(chat_id, user_id, sender, " ".join(parts[1:]))
    elif cmd in ["open", "открытые"]:
        await handle_open_tickets(chat_id, user_id)
    elif cmd in ["closed", "закрытые"]:
        await handle_closed_tickets(chat_id, user_id)
    elif cmd in ["tickets", "заявки", "все"]:
        await handle_my_tickets(chat_id, user_id)
    elif cmd in ["new", "создать"]:
        await handle_new_ticket(chat_id, user_id)
    elif cmd == "logout":
        await handle_logout(chat_id, user_id)
    elif cmd == "cancel":
        reset_user_state(user_id)
        cartridge_user_states.pop(user_id, None)
        await handle_start(chat_id, user_id, sender)
    elif cmd == "help":
        await handle_callback_action(chat_id, user_id, "cmd", "help", None)
    elif cmd == "start":
        await handle_start(chat_id, user_id, sender)
    elif cmd == "ticket" and len(parts) >= 2:
        try:
            await handle_ticket_details(chat_id, user_id, int(parts[1].lstrip("#")))
        except:
            await send_text(chat_id, "❌ /ticket #7", create_main_keyboard(), delete_before=True)
    else:
        await send_text(chat_id, "❓ /start", create_main_keyboard(), delete_before=True)


# =============================================================================
# МАРШРУТИЗАЦИЯ
# =============================================================================

async def handle_message(update: Dict):
    msg = update.get("message", {})
    sender = msg.get("sender", {})
    recipient = msg.get("recipient", {})
    body = msg.get("body", {})
    chat_id = recipient.get("chat_id")
    user_id = sender.get("user_id")
    text = body.get("text", "").strip()
    message_id = msg.get('message_id')

    if not chat_id or user_id is None:
        return

    state = get_user_state(user_id)

    # 🔥 Обработка ввода кабинета для заявки на картридж
    crt_state = cartridge_user_states.get(user_id, {})
    if crt_state.get("waiting_for") == "cabinet":
        await handle_cartridge_cabinet(chat_id, user_id, text, message_id)
        return

    if state.get("waiting_for") == "login_username":
        set_user_state(user_id, waiting_for="login_password", login_temp=text)
        text = (
            "🔐 Пароль\n\n"
            "Введите ваш пароль:"
        )
        await send_text(chat_id, text, create_cancel_keyboard(), delete_before=True)
        if message_id:
            await delete_user_message(chat_id, message_id)
        return

    elif state.get("waiting_for") == "login_password":
        login_temp = state.get("login_temp")
        if login_temp:
            if message_id:
                await delete_user_message(chat_id, message_id)
            await complete_login(chat_id, user_id, sender, login_temp, text, message_id)
        else:
            await send_text(chat_id, "❌ Ошибка авторизации, попробуйте /login", create_auth_keyboard(), delete_before=True)
        return

    if text.startswith("/"):
        await handle_command(chat_id, user_id, sender, text)
    else:
        if state.get("waiting_for") == "ticket_text":
            await create_ticket_from_message(chat_id, user_id, text, message_id)
        elif state.get("waiting_for") == "comment" and state.get("ticket_id"):
            await add_comment_to_ticket(chat_id, user_id, state["ticket_id"], text)
        elif state.get("waiting_for") == "confirm_close" and state.get("ticket_id"):
            if text.lower() in ["да", "yes"]:
                await close_ticket(chat_id, user_id, state["ticket_id"])
            else:
                await send_text(chat_id, "❌ Отменено", create_main_keyboard(), delete_before=True)
            reset_user_state(user_id)
        else:
            await send_text(chat_id, "❓ Нажмите /start или кнопку", create_main_keyboard(), delete_before=True)


async def handle_callback_update(update: Dict):
    msg = update.get("message", {})
    recipient = msg.get("recipient", {})
    chat_id = recipient.get("chat_id")
    callback_data = update.get("callback", {})
    user_info = callback_data.get("user", {})
    user_id = user_info.get("user_id")
    if not user_id:
        sender = msg.get("sender", {})
        user_id = sender.get("user_id")
    logger.info(f"🔘 Callback: user_id={user_id}, chat_id={chat_id}")
    if chat_id and user_id is not None:
        await process_callback(chat_id, user_id, callback_data)
    else:
        logger.error(f"❌ Не удалось получить user_id или chat_id: {update}")


async def route_update(update: Dict):
    update_type = update.get("update_type")

    logger.info(f"📥 Получено событие: {update_type}")

    if update_type == "message_created":
        await handle_message(update)

    elif update_type == "message_callback":
        await handle_callback_update(update)

    # 🔥 ИСПРАВЛЕННАЯ ОБРАБОТКА bot_started
    elif update_type == "bot_started":
        logger.info("🤖 СОБЫТИЕ BotStarted ПОЛУЧЕНО!")

        # 🔥 В bot_started chat_id и user_id на верхнем уровне!
        chat_id = update.get('chat_id')
        user_id = update.get('user_id')
        user_info = update.get('user', {})  # Дополнительная информация

        logger.info(f"🤖 BotStarted: chat_id={chat_id}, user_id={user_id}")

        if chat_id and user_id is not None:
            logger.info(f"✅ Вызываем handle_bot_started()")
            # Передаём user_info как sender для совместимости
            await handle_bot_started(chat_id, user_id, sender=user_info)
        else:
            logger.error(f"❌ Нет chat_id или user_id: {update}")

    else:
        logger.debug(f"⚪ Неизвестный тип: {update_type}")


# =============================================================================
# POLLING
# =============================================================================

async def poll_updates():
    marker = get_repos()['state'].get('polling_marker')
    logger.info(f"Polling start (marker={marker})")

    while True:
        try:
            # 🔥 ОБРАБОТКА ОЧЕРЕДИ СООБЩЕНИЙ
            while True:
                try:
                    msg = message_queue.get_nowait()
                    chat_id = msg.get('chat_id')
                    text = msg.get('text')
                    if chat_id and text:
                        logger.info(f"📤 Отправка сообщения из очереди: chat_id={chat_id}")
                        await bot.send_message(chat_id=chat_id, text=text)
                        logger.info(f"✅ Сообщение отправлено: chat_id={chat_id}")
                except queue.Empty:
                    break
                except Exception as e:
                    logger.error(f"❌ Ошибка отправки из очереди: {e}", exc_info=True)

            response = await bot.get_updates(limit=100, timeout=30, marker=marker)
            updates = response.get("updates", []) if isinstance(response, dict) else []

            if isinstance(response, dict) and response.get("marker"):
                marker = response["marker"]
                get_repos()['state'].set('polling_marker', str(marker))

            if updates:
                for update in updates:
                    try:
                        await route_update(update)
                    except Exception as e:
                        logger.error(f"❌ Error: {e}")
            else:
                await asyncio.sleep(2)

        except asyncio.CancelledError:
            break
        except Exception as e:
            logger.error(f"❌ Polling error: {e}")
            await asyncio.sleep(5)


# =============================================================================
# MAIN
# =============================================================================

async def main():
    logger.info("🚀 Start Zammad + MAX Bot")

    try:
        global bot, zammad, cartridge_repo, cartridge_service

        if not config.is_valid:
            logger.error("❌ Check .env")
            return

        # Инициализация основной БД
        init_database("sqlite:///bot.db")

        # 🔥 Инициализация БД картриджей
        global cartridge_engine, cartridge_session
        cartridge_engine, cartridge_session = init_cartridge_database(config.cartridge_db_url)
        cartridge_repo = CartridgeRepository(cartridge_session)

        # 🔥 Инициализация сервиса картриджей
        if config.cartridge_chat_id:
            cartridge_service = CartridgeService(cartridge_repo, config.cartridge_chat_id)
            logger.info(f"✅ Сервис картриджей инициализирован (чат: {config.cartridge_chat_id})")
        else:
            logger.warning("⚠️ CARTRIDGE_CHAT_ID не настроен в .env")

        bot = Bot(token=config.max_bot_token)
        zammad = ZammadClient()
        init_mapper()

        logger.info("✅ Bot ready")

        try:
            await bot.delete_webhook()
        except:
            pass

        # 🔥 ЗАПУСК WEBHOOK СЕРВЕРА
        if config.enable_webhook:
            logger.info("🔗 Запуск webhook сервера...")

            from webhook_server import run_webhook_server

            def start_webhook():
                asyncio.run(run_webhook_server(
                    bot=bot,
                    host=config.webhook_host,
                    port=config.webhook_port
                ))

            webhook_thread = threading.Thread(target=start_webhook, daemon=True)
            webhook_thread.start()
            logger.info(f"✅ Webhook сервер запущен в фоне на порту {config.webhook_port}")

        await poll_updates()

    except KeyboardInterrupt:
        logger.info("👋 Ctrl+C")
    except Exception as e:
        logger.error(f"💥 Critical: {e}")
    finally:
        logger.info("🔄 Shutdown")


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        logger.info("👋 Stopped")