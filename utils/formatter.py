"""
Форматирование ответов
"""

from typing import List, Dict, Any
from datetime import datetime

STATE_ID_MAP = {
    1: {"name": "Новая", "icon": "🆕"},
    2: {"name": "В работе", "icon": "🟡"},
    3: {"name": "На паузе", "icon": "⏸️"},
    4: {"name": "Закрыта", "icon": "🔴"},
    5: {"name": "Удалена", "icon": "❌"},
}


def _get_state_display(state_id: Any):
    try:
        state_id = int(state_id)
    except:
        return "❓", "Unknown"

    info = STATE_ID_MAP.get(state_id)
    return (info["icon"], info["name"]) if info else ("❓", f"ID:{state_id}")


def format_ticket_list(tickets: List[Dict]) -> str:
    if not tickets:
        return "📭 Нет заявок"

    lines = ["📋 **Ваши заявки:**\n"]

    for ticket in tickets:
        if not isinstance(ticket, dict):
            continue

        state_id = ticket.get("state_id") or ticket.get("state")
        icon, state_name = _get_state_display(state_id)

        number = ticket.get("id", "?")
        title = ticket.get("title", "Без заголовка")[:50]

        date_str = ticket.get("updated_at") or ticket.get("created_at") or ""
        if date_str:
            try:
                dt = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                date_formatted = dt.strftime("%d.%m %H:%M")
            except:
                date_formatted = date_str[:16]
        else:
            date_formatted = "неизвестно"

        lines.append(f"{icon} **#{number}** | {title} | {state_name}\n   🕐 {date_formatted}")

    return "\n\n".join(lines)


def format_ticket_details(ticket: Dict) -> str:
    if not ticket:
        return "❌ Не удалось загрузить детали"

    state_id = ticket.get("state_id") or ticket.get("state")
    icon, state_name = _get_state_display(state_id)

    number = ticket.get("id", "?")
    title = ticket.get("title", "Без заголовка")

    lines = [
        f"🎫 **Заявка #{number}**",
        f"",
        f"📌 {title}",
        f"📊 Статус: {icon} {state_name}",
    ]

    created = ticket.get("created_at", "")
    if created:
        try:
            dt = datetime.fromisoformat(created.replace("Z", "+00:00"))
            lines.append(f"🕐 Создана: {dt.strftime('%d.%m.%Y %H:%M')}")
        except:
            pass

    return "\n".join(lines)