import logging
import re
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

from config import config

logger = logging.getLogger(__name__)


@dataclass
class ProcessedMessage:
    """Результат обработки сообщения"""
    is_command: bool
    command: Optional[str]
    content: str
    attachments: List[Dict[str, Any]]
    metadata: Dict[str, Any]


class MessageProcessor:
    """Утилиты для обработки входящих сообщений"""

    # Паттерны команд
    COMMAND_PATTERNS = {
        "new": re.compile(r"^/(new|создать|новая)\b", re.I),
        "tickets": re.compile(r"^/(tickets|заявки|мои)\b", re.I),
        "ticket": re.compile(r"^/(ticket|тикет|заявка)\s*#?(\d+)", re.I),
        "help": re.compile(r"^/(help|помощь|справка)\b", re.I),
        "cancel": re.compile(r"^(отмена|cancel|❌|назад)$", re.I),
    }

    @classmethod
    def parse(cls, text: str, attachments: Optional[List] = None) -> ProcessedMessage:
        """Разобрать сообщение на компоненты"""
        text = text.strip() if text else ""
        attachments = attachments or []

        # Проверка на команду
        for cmd_name, pattern in cls.COMMAND_PATTERNS.items():
            match = pattern.match(text)
            if match:
                return ProcessedMessage(
                    is_command=True,
                    command=cmd_name,
                    content=text,
                    attachments=attachments,
                    metadata={"groups": match.groups() if match.groups() else ()}
                )

        # Обычное сообщение
        return ProcessedMessage(
            is_command=False,
            command=None,
            content=text,
            attachments=attachments,
            metadata={}
        )

    @classmethod
    def extract_ticket_number(cls, text: str) -> Optional[int]:
        """Извлечь номер тикета из текста: #123, 123, ticket 123"""
        patterns = [
            r"#?(\d{3,})",  # #123 или 123
            r"ticket\s*#?(\d+)",  # ticket 123
            r"заявка\s*#?(\d+)",  # заявка 123
        ]
        for pattern in patterns:
            match = re.search(pattern, text, re.I)
            if match:
                try:
                    return int(match.group(1))
                except ValueError:
                    continue
        return None

    @classmethod
    def sanitize(cls, text: str, max_length: int = 4000) -> str:
        """Очистить и обрезать текст"""
        # Убираем лишние пробелы и переносы
        text = re.sub(r"\s+", " ", text.strip())
        # Обрезаем если нужно
        return text[:max_length]

    @classmethod
    def format_for_zammad(cls, message: ProcessedMessage) -> Dict[str, Any]:
        """Подготовить данные для отправки в Zammad"""
        return {
            "body": cls.sanitize(message.content),
            "attachments": [
                {
                    "filename": att.get("filename", "file"),
                    "data": att.get("base64_data", ""),
                    "mime_type": att.get("content_type", "application/octet-stream"),
                }
                for att in message.attachments
            ],
            "metadata": message.metadata,
        }

    @classmethod
    def is_cancel(cls, text: str) -> bool:
        """Проверка на команду отмены"""
        return bool(cls.COMMAND_PATTERNS["cancel"].match(text.strip()))