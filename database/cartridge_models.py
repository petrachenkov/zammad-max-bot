"""
Модели базы данных для заявок на заправку картриджей
Отдельная БД: cartridges.db
"""

from sqlalchemy import Column, Integer, String, DateTime, Boolean, Text, ForeignKey, create_engine
from sqlalchemy.orm import relationship, declarative_base, sessionmaker
from datetime import datetime

Base = declarative_base()


class CartridgeRequest(Base):
    """🔥 Активные заявки на заправку картриджей"""
    __tablename__ = 'cartridge_requests'

    id = Column(Integer, primary_key=True, autoincrement=True)
    cartridge_id = Column(String(6), unique=True, nullable=False, index=True)  # 6 цифр

    # Данные пользователя
    max_user_id = Column(Integer, nullable=False)
    chat_id = Column(Integer, nullable=False)
    fio = Column(String(255), nullable=False)
    cabinet = Column(String(50), nullable=False)

    # Статус заявки
    status = Column(String(20), default='pending')  # pending, received, cancelled, archived
    received_at = Column(DateTime, nullable=True)
    received_by_admin_id = Column(Integer, nullable=True)  # ID админа кто принял

    # Метаданные
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def __repr__(self):
        return f"<CartridgeRequest(cartridge_id={self.cartridge_id}, fio={self.fio}, cabinet={self.cabinet})>"


class CartridgeArchive(Base):
    """🔥 Архив выполненных заявок (после генерации Excel)"""
    __tablename__ = 'cartridge_archive'

    id = Column(Integer, primary_key=True, autoincrement=True)
    cartridge_id = Column(String(6), nullable=False, index=True)

    # Данные пользователя
    max_user_id = Column(Integer, nullable=False)
    fio = Column(String(255), nullable=False)
    cabinet = Column(String(50), nullable=False)

    # Информация о заправке
    received_at = Column(DateTime, nullable=False)
    received_by_admin_id = Column(Integer, nullable=True)
    report_id = Column(Integer, ForeignKey('generated_reports.id'), nullable=True)  # Связь с отчётом

    # Метаданные
    archived_at = Column(DateTime, default=datetime.utcnow)

    def __repr__(self):
        return f"<CartridgeArchive(cartridge_id={self.cartridge_id}, archived_at={self.archived_at})>"


class GeneratedReport(Base):
    """🔥 История сгенерированных Excel-отчётов"""
    __tablename__ = 'generated_reports'

    id = Column(Integer, primary_key=True, autoincrement=True)
    report_name = Column(String(255), nullable=False)  # Например: "cartridges_2026-04-29.xlsx"
    file_path = Column(String(500), nullable=False)  # Путь к файлу
    generated_at = Column(DateTime, default=datetime.utcnow)
    generated_by_admin_id = Column(Integer, nullable=True)

    # Статистика
    cartridges_count = Column(Integer, default=0)

    def __repr__(self):
        return f"<GeneratedReport(name={self.report_name}, count={self.cartridges_count})>"


# =============================================================================
# Инициализация отдельной БД
# =============================================================================

def init_cartridge_database(db_url: str = "sqlite:///cartridges.db"):
    """Инициализация БД картриджей"""
    engine = create_engine(db_url, echo=False)
    Base.metadata.create_all(bind=engine)
    SessionLocal = sessionmaker(bind=engine)
    return engine, SessionLocal