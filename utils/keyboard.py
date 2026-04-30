"""
Утилиты для создания кнопок в MAX Messenger
"""

from typing import List, Dict, Optional, Union


class KeyboardButton:
    """Кнопка клавиатуры"""

    def __init__(self, text: str, callback: Optional[str] = None, url: Optional[str] = None):
        self.text = text
        self.callback = callback  # Для inline кнопок
        self.url = url  # Для веб-ссылок

    def to_dict(self) -> Dict:
        """Конвертация в формат MAX API"""
        btn = {"text": self.text}
        if self.callback:
            btn["callback_data"] = self.callback
        if self.url:
            btn["url"] = self.url
        return btn


class Keyboard:
    """Клавиатура для бота"""

    def __init__(self, inline: bool = False):
        self.inline = inline
        self.rows: List[List[KeyboardButton]] = []

    def add_row(self, *buttons: Union[str, KeyboardButton]):
        """Добавить строку кнопок"""
        row = []
        for btn in buttons:
            if isinstance(btn, str):
                row.append(KeyboardButton(text=btn, callback=f"/{btn.lower().replace(' ', '_')}"))
            else:
                row.append(btn)
        self.rows.append(row)
        return self

    def add_button(self, text: str, callback: Optional[str] = None, url: Optional[str] = None):
        """Добавить одну кнопку в новую строку"""
        return self.add_row(KeyboardButton(text=text, callback=callback, url=url))

    def to_dict(self) -> Dict:
        """Конвертация в формат MAX API"""
        keyboard = {
            "inline_keyboard": self.rows if self.inline else None,
            "keyboard": [[btn.to_dict() for btn in row] for row in self.rows] if not self.inline else None,
            "one_time_keyboard": True,  # Скрыть после нажатия
            "resize_keyboard": True,  # Адаптивный размер
        }
        # Убираем пустые поля
        return {k: v for k, v in keyboard.items() if v is not None}

    @classmethod
    def main_menu(cls) -> 'Keyboard':
        """Главное меню бота"""
        kb = cls(inline=False)
        kb.add_row("🎫 Новые заявки", "🟡 Открытые", "🔴 Закрытые")
        kb.add_row("📋 Все заявки", "✍️ Создать")
        kb.add_row("👤 Профиль", "🔐 Выйти")
        return kb

    @classmethod
    def auth_menu(cls) -> 'Keyboard':
        """Меню до авторизации"""
        kb = cls(inline=False)
        kb.add_row("🔐 Войти")
        kb.add_row("❓ Помощь")
        return kb

    @classmethod
    def ticket_actions(cls, ticket_id: int) -> 'Keyboard':
        """Кнопки действий с заявкой"""
        kb = cls(inline=True)
        kb.add_row(
            KeyboardButton("📝 Добавить комментарий", callback=f"/comment_{ticket_id}"),
            KeyboardButton("🔄 Обновить", callback=f"/refresh_{ticket_id}")
        )
        kb.add_row(
            KeyboardButton("🔴 Закрыть", callback=f"/close_{ticket_id}"),
            KeyboardButton("⬅️ Назад", callback="/tickets")
        )
        return kb

    @classmethod
    def cancel_keyboard(cls) -> 'Keyboard':
        """Клавиатура с кнопкой отмены"""
        kb = cls(inline=False)
        kb.add_row("❌ Отмена")
        return kb


def create_reply_keyboard(*button_texts: str, one_time: bool = True) -> Dict:
    """Быстрое создание простой клавиатуры"""
    return {
        "keyboard": [[{"text": text}] for text in button_texts],
        "one_time_keyboard": one_time,
        "resize_keyboard": True,
    }


def create_inline_keyboard(*buttons: tuple) -> Dict:
    """
    Быстрое создание inline-клавиатуры
    buttons: [("Текст", "callback"), ...]
    """
    return {
        "inline_keyboard": [
            [{"text": text, "callback_data": cb} for text, cb in [buttons[i:i+2] for i in range(0, len(buttons), 2)][j:j+2]]
            for j in range(0, len([buttons[i:i+2] for i in range(0, len(buttons), 2)]), 2)
        ] if buttons else []
    }