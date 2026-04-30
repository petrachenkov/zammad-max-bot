"""
Конфигурация бота
"""

import os
from dotenv import load_dotenv

load_dotenv()

class Config:
    # MAX Bot
    max_bot_token = os.getenv("MAX_BOT_TOKEN", "")

    # Zammad
    zammad_url = os.getenv("ZAMMAD_URL", "")
    zammad_token = os.getenv("ZAMMAD_TOKEN", "")

    # Database
    database_url = os.getenv("DATABASE_URL", "sqlite:///bot.db")

    # Bot settings
    default_group = os.getenv("DEFAULT_GROUP", "IT")
    default_priority = os.getenv("DEFAULT_PRIORITY", "2 normal")

    # Webhook
    enable_webhook = os.getenv("ENABLE_WEBHOOK", "false").lower() == "true"
    webhook_host = os.getenv("WEBHOOK_HOST", "0.0.0.0")
    webhook_port = int(os.getenv("WEBHOOK_PORT", "8080"))
    webhook_secret = os.getenv("WEBHOOK_SECRET", "")

    # 🔥 Картриджи
    cartridge_chat_id = int(os.getenv("CARTRIDGE_CHAT_ID", "0"))  # ID специального чата для админов
    cartridge_db_url = os.getenv("CARTRIDGE_DB_URL", "sqlite:///cartridges.db")
    cartridge_reports_dir = os.getenv("CARTRIDGE_REPORTS_DIR", "reports")

    @property
    def is_valid(self) -> bool:
        return bool(self.max_bot_token and self.zammad_url and self.zammad_token)

config = Config()