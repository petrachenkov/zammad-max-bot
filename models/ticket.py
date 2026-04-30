from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, List, Dict, Any
from enum import Enum


class TicketState(str, Enum):
    """Статусы тикетов Zammad"""
    NEW = "new"
    OPEN = "open"
    PENDING = "pending"
    SOLVED = "solved"
    CLOSED = "closed"

    @property
    def emoji(self) -> str:
        """Эмодзи для статуса"""
        mapping = {
            self.NEW: "🆕",
            self.OPEN: "🟡",
            self.PENDING: "⏸️",
            self.SOLVED: "🟢",
            self.CLOSED: "🔴",
        }
        return mapping.get(self, "📋")

    @property
    def label_ru(self) -> str:
        """Человекочитаемое название"""
        mapping = {
            self.NEW: "Новый",
            self.OPEN: "В работе",
            self.PENDING: "Ожидает",
            self.SOLVED: "Решён",
            self.CLOSED: "Закрыт",
        }
        return mapping.get(self, "Неизвестно")


@dataclass
class TicketArticle:
    """Сообщение/статья в тикете"""
    id: int
    body: str
    sender: str  # Customer | Agent
    created_at: datetime
    internal: bool = False
    attachments: List[Dict[str, Any]] = field(default_factory=list)

    @classmethod
    def from_zammad(cls, data: Dict[str, Any]) -> "TicketArticle":
        """Создать из ответа Zammad API"""
        return cls(
            id=data.get("id"),
            body=data.get("body", ""),
            sender=data.get("sender", "Customer"),
            created_at=datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))
            if data.get("created_at") else datetime.now(),
            internal=data.get("internal", False),
            attachments=data.get("attachments", []),
        )


@dataclass
class TicketInfo:
    """Информация о тикете"""
    id: int
    number: str
    title: str
    state: TicketState
    group: str
    priority: str
    customer_email: str
    created_at: datetime
    updated_at: datetime
    articles: List[TicketArticle] = field(default_factory=list)

    @property
    def url(self) -> str:
        """Ссылка на тикет в Zammad"""
        from config import config
        return f"{config.zammad_url}/#ticket/zoom/{self.id}"

    @classmethod
    def from_zammad(cls, data: Dict[str, Any]) -> "TicketInfo":
        """Создать из ответа Zammad API"""
        return cls(
            id=data.get("id"),
            number=str(data.get("number", "")),
            title=data.get("title", "Без заголовка"),
            state=TicketState(data.get("state", "new")),
            group=data.get("group", "Users"),
            priority=data.get("priority", "2 normal"),
            customer_email=data.get("customer_email", ""),
            created_at=datetime.fromisoformat(data["created_at"].replace("Z", "+00:00"))
            if data.get("created_at") else datetime.now(),
            updated_at=datetime.fromisoformat(data["updated_at"].replace("Z", "+00:00"))
            if data.get("updated_at") else datetime.now(),
        )

    def to_short_summary(self) -> str:
        """Краткое представление для списка"""
        return (
            f"{self.state.emoji} \n #{self.number} — {self.title[:50]}{'...' if len(self.title) > 50 else ''}\n"
            f"Создана: {self.created_at.strftime('%d.%m %H:%M')} | 👥 {self.group}"
        )

    def to_detailed_view(self) -> str:
        """Полное представление тикета"""
        articles_preview = ""
        if self.articles:
            last_article = self.articles[-1]
            preview = last_article.body[:150].replace("\n", " ")
            articles_preview = f"\n\n💬 Последнее: _{preview}{'...' if len(last_article.body) > 150 else ''}_"

        return (
            f"🎫 *Заявка #{self.number}*\n"
            f"{'=' * 40}\n"
            f"📌 {self.title}\n"
            f"📊 Статус: {self.state.emoji} {self.state.label_ru}\n"
            f"👥 Группа: {self.group}\n"
            f"🔖 Приоритет: {self.priority}\n"
            f"📅 Создана: {self.created_at.strftime('%d.%m.%Y %H:%M')}\n"
            f"🔄 Обновлено: {self.updated_at.strftime('%d.%m %H:%M')}\n"
            f"{articles_preview}\n"
            f"\n🔗 [Открыть в Zammad]({self.url})"
        )