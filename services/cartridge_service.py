"""
Бизнес-логика для работы с заявками на картриджи
"""

import logging
import os
from typing import Dict, Any, Optional, List

from database.cartridge_repository import CartridgeRepository
from utils.excel_generator import generate_cartridge_excel
from maxapi.types import CallbackButton, InputMedia
from maxapi.utils.inline_keyboard import InlineKeyboardBuilder

logger = logging.getLogger(__name__)


class CartridgeService:
    """Сервис для управления заявками на картриджи"""

    def __init__(self, cartridge_repo: CartridgeRepository, cartridge_chat_id: int):
        self.repo = cartridge_repo
        self.cartridge_chat_id = cartridge_chat_id

    def create_cartridge_keyboard(self, cartridge_id: str) -> list:
        """Создать клавиатуру для заявки в админ-чат"""
        builder = InlineKeyboardBuilder()
        builder.row(
            CallbackButton(text="✅ Получен", payload=f"crt:received:{cartridge_id}"),
            CallbackButton(text="❌ Отмена", payload=f"crt:cancel:{cartridge_id}"),
        )
        return [builder.as_markup()]

    def create_admin_cartridge_keyboard(self) -> list:
        """Клавиатура для админ-чата"""
        builder = InlineKeyboardBuilder()
        builder.row(
            CallbackButton(text="📋_pending", payload="crt:list_pending"),
            CallbackButton(text="📊 Генерировать Excel", payload="crt:generate_excel"),
        )
        builder.row(
            CallbackButton(text="📁 Архив отчётов", payload="crt:list_reports"),
            CallbackButton(text="❓ Помощь", payload="crt:help"),
        )
        return [builder.as_markup()]

    def create_help_keyboard(self) -> list:
        """Клавиатура под справкой с быстрыми командами"""
        builder = InlineKeyboardBuilder()
        builder.row(
            CallbackButton(text="📋 Список заявок", payload="crt:list_pending"),
        )
        builder.row(
            CallbackButton(text="📊 Сгенерировать отчёт", payload="crt:generate_excel"),
        )
        builder.row(
            CallbackButton(text="📁 Архив отчётов", payload="crt:list_reports"),
        )
        return [builder.as_markup()]

    def get_help_text(self) -> str:
        """Текст справки по командам админ-чата (без markdown)"""
        return """📋 СПРАВКА ПО КОМАНДАМ КАРТРИДЖЕЙ

🖨️ ЗАЯВКИ ОТ ПОЛЬЗОВАТЕЛЕЙ:
Когда пользователь создаёт заявку на заправку картриджа, в этот чат приходит сообщение с информацией:
- ФИО пользователя
- Номер кабинета
- Код картриджа (6 цифр)
- Время заявки

Под заявкой две кнопки:
✅ Получен — подтвердить получение картриджа
❌ Отмена — отменить заявку

📋 КОМАНДЫ АДМИНА:

/list_pending — Показать все заявки
Раздел "Готовы к отчёту" — заявки со статусом "Получен"
Раздел "Ожидают получения" — заявки ждут подтверждения

/generate_excel — Создать Excel-отчёт
Берёт все заявки со статусом "Получен"
Генерирует таблицу с 4 столбцами:
1. Инициалы Фамилия
2. Кабинет
3. ID картриджа
4. Подпись (пустой)
После генерации записи перемещаются в архив

/list_reports — Показать список архивных отчётов
Выводит список всех сгенерированных Excel-файлов
У каждого файла есть номер для скачивания

/report <номер> — Скачать конкретный отчёт
Пример: /report 1
Отправляет выбранный Excel-файл в чат

/help — Показать эту справку

📊 ПРИМЕР РАБОЧЕГО ПРОЦЕССА:
1. Пользователь создаёт заявку → статус "pending"
2. Админ нажимает "Получен" → статус "received"
3. Накопилось несколько заявок → /generate_excel
4. Бот создаёт Excel и отправляет в чат
5. Записи перемещаются в архив
6. В любой момент можно скачать старый отчёт: /report <номер>

🔐 ДОСТУП:
Все команды работают только в этом чате.
В других чатах команды недоступны."""

    def format_request_message(self, request: Dict) -> str:
        """Форматировать сообщение заявки для админ-чата"""
        return (
            f"🆕 Новая заявка на заправку картриджа\n\n"
            f"👤 ФИО: {request['fio']}\n"
            f"🚪 Кабинет: {request['cabinet']}\n"
            f"🔢 Код картриджа: {request['cartridge_id']}\n\n"
            f"⏰ Время заявки: {request['created_at'][:16] if request.get('created_at') else 'Н/Д'}\n\n"
            f"Нажмите кнопку ниже для подтверждения получения."
        )

    def format_excel_report_message(self, report: Dict, count: int) -> str:
        """Форматировать сообщение о сгенерированном отчёте"""
        return (
            f"📊 Отчёт по заправке картриджей\n\n"
            f"📄 Файл: {report['report_name']}\n"
            f"🔢 Картриджей: {count}\n"
            f"🕐 Сгенерирован: {report['generated_at'][:16]}\n\n"
            f"Записи перемещены в архив."
        )

    async def process_new_request(
        self,
        cartridge_id: str,
        max_user_id: int,
        chat_id: int,
        fio: str,
        cabinet: str,
        bot
    ) -> Dict:
        """Обработка новой заявки от пользователя"""
        request = self.repo.create_request(
            cartridge_id=cartridge_id,
            max_user_id=max_user_id,
            chat_id=chat_id,
            fio=fio,
            cabinet=cabinet,
        )

        user_message = (
            f"✅ Код для картриджа: {cartridge_id}\n\n"
            f"📝 Напишите этот код на небольшую бумажечку и приклейте к картриджу.\n"
            f"🚚 Наш сотрудник скоро заберет ваш картридж на заправку."
        )
        await bot.send_message(chat_id=chat_id, text=user_message)

        admin_message = self.format_request_message(request)
        keyboard = self.create_cartridge_keyboard(cartridge_id)
        await bot.send_message(
            chat_id=self.cartridge_chat_id,
            text=admin_message,
            attachments=keyboard
        )

        logger.info(f"✅ Заявка на картридж {cartridge_id} обработана")
        return request

    async def process_received(
        self,
        cartridge_id: str,
        admin_id: int,
        bot
    ) -> bool:
        """Обработка кнопки 'Получен' от админа"""
        success = self.repo.mark_as_received(cartridge_id, admin_id)

        if success:
            await bot.send_message(
                chat_id=self.cartridge_chat_id,
                text=f"✅ Картридж {cartridge_id} получен и добавлен в очередь на заправку."
            )
            logger.info(f"✅ Картридж {cartridge_id} отмечен как полученный")

        return success

    async def process_cancel(
        self,
        cartridge_id: str,
        bot
    ) -> bool:
        """Обработка кнопки 'Отмена' от админа"""
        success = self.repo.cancel_request(cartridge_id)

        if success:
            await bot.send_message(
                chat_id=self.cartridge_chat_id,
                text=f"❌ Заявка на картридж {cartridge_id} отменена."
            )
            logger.info(f"❌ Заявка {cartridge_id} отменена")

        return success

    async def generate_excel_report(
        self,
        admin_id: int,
        bot,
        output_dir: str = "reports"
    ) -> Optional[Dict]:
        """Генерация Excel-отчёта по полученным картриджам"""
        requests = self.repo.get_received_requests()

        if not requests:
            await bot.send_message(
                chat_id=self.cartridge_chat_id,
                text="⚠️ Нет заявок на заправку для формирования отчёта."
            )
            return None

        try:
            filepath = generate_cartridge_excel(requests, output_dir=output_dir)
        except ImportError as e:
            await bot.send_message(
                chat_id=self.cartridge_chat_id,
                text=f"❌ Ошибка: {e}\nУстановите openpyxl: pip install openpyxl"
            )
            return None

        filename = os.path.basename(filepath)
        report = self.repo.create_report(
            report_name=filename,
            file_path=filepath,
            admin_id=admin_id,
            count=len(requests),
        )

        self.repo.archive_pending_requests(report['id'])

        # ОТПРАВКА ФАЙЛА ЧЕРЕЗ InputMedia
        try:
            await bot.send_message(
                chat_id=self.cartridge_chat_id,
                text=self.format_excel_report_message(report, len(requests)),
                attachments=[
                    InputMedia(path=filepath)
                ]
            )

            logger.info(f"✅ Отчёт {filename} сгенерирован и отправлен ({len(requests)} картриджей)")
            return report

        except Exception as e:
            logger.error(f"❌ Ошибка отправки файла: {e}", exc_info=True)

            # Пробуем через upload_media
            try:
                media = InputMedia(filepath)
                attachment = await bot.upload_media(media)

                await bot.send_message(
                    chat_id=self.cartridge_chat_id,
                    text=self.format_excel_report_message(report, len(requests)),
                    attachments=[attachment]
                )

                logger.info(f"✅ Отчёт {filename} отправлен через upload_media")
                return report

            except Exception as e2:
                logger.error(f"❌ Ошибка отправки файла (вариант 2): {e2}", exc_info=True)
                await bot.send_message(
                    chat_id=self.cartridge_chat_id,
                    text=f"❌ Ошибка отправки файла: {e2}\n\nФайл сохранён: {filepath}"
                )
                return None

    async def list_reports(self, admin_id: int, bot) -> str:
        """Список всех сгенерированных отчётов"""
        reports = self.repo.get_all_reports()

        if not reports:
            return "📁 Архив отчётов пуст."

        lines = ["📁 Архив отчётов по картриджам\n"]
        for i, r in enumerate(reports, 1):
            lines.append(
                f"{i}. {r['report_name']} — {r['cartridges_count']} картриджей "
                f"({r['generated_at'][:16]})"
            )

        lines.append("\n📋 Для получения файла отправьте: /report <номер>")
        return "\n".join(lines)

    async def send_report_by_index(
        self,
        index: int,
        admin_id: int,
        bot
    ) -> bool:
        """Отправить конкретный отчёт по индексу"""
        reports = self.repo.get_all_reports()

        if index < 1 or index > len(reports):
            await bot.send_message(
                chat_id=self.cartridge_chat_id,
                text=f"❌ Отчёт #{index} не найден. Доступно отчётов: {len(reports)}"
            )
            return False

        report = reports[index - 1]
        filepath = report['file_path']

        if not os.path.exists(filepath):
            await bot.send_message(
                chat_id=self.cartridge_chat_id,
                text=f"❌ Файл не найден: {filepath}"
            )
            return False

        # ОТПРАВКА ФАЙЛА ЧЕРЕЗ InputMedia
        try:
            await bot.send_message(
                chat_id=self.cartridge_chat_id,
                text=f"📄 {report['report_name']}\n\n{report['cartridges_count']} картриджей",
                attachments=[
                    InputMedia(path=filepath)
                ]
            )

            logger.info(f"✅ Отправлен отчёт: {report['report_name']}")
            return True

        except Exception as e:
            logger.error(f"❌ Ошибка отправки файла: {e}", exc_info=True)
            return False

    async def show_help(self, bot) -> None:
        """Показать справку по командам"""
        keyboard = self.create_help_keyboard()

        await bot.send_message(
            chat_id=self.cartridge_chat_id,
            text=self.get_help_text(),
            attachments=keyboard
        )