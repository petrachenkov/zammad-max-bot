"""
Репозиторий для работы с БД картриджей
"""

import logging
import random
import string
from typing import Optional, List, Dict
from datetime import datetime
from contextlib import contextmanager

from database.cartridge_models import CartridgeRequest, CartridgeArchive, GeneratedReport

logger = logging.getLogger(__name__)


class CartridgeRepository:
    """Операции с заявками на картриджи"""

    def __init__(self, SessionLocal):
        self.SessionLocal = SessionLocal

    @contextmanager
    def get_session(self):
        """Контекстный менеджер для сессии"""
        session = self.SessionLocal()
        try:
            yield session
            session.commit()
        except Exception as e:
            session.rollback()
            logger.error(f"❌ Ошибка БД картриджей: {e}")
            raise
        finally:
            session.close()

    def generate_unique_cartridge_id(self) -> str:
        """🔥 Генерация уникального 6-значного кода"""
        while True:
            code = ''.join(random.choices(string.digits, k=6))
            with self.get_session() as session:
                exists = session.query(CartridgeRequest).filter(
                    CartridgeRequest.cartridge_id == code
                ).first()
                if not exists:
                    return code

    def create_request(
        self,
        cartridge_id: str,
        max_user_id: int,
        chat_id: int,
        fio: str,
        cabinet: str
    ) -> Dict:
        """Создать новую заявку"""
        with self.get_session() as session:
            request = CartridgeRequest(
                cartridge_id=cartridge_id,
                max_user_id=max_user_id,
                chat_id=chat_id,
                fio=fio.strip(),
                cabinet=cabinet.strip(),
                status='pending',
                created_at=datetime.utcnow(),
            )
            session.add(request)

            logger.info(f"✅ Создана заявка на картридж: {cartridge_id} ({fio}, каб.{cabinet})")

            return {
                'id': request.id,
                'cartridge_id': request.cartridge_id,
                'fio': request.fio,
                'cabinet': request.cabinet,
                'status': request.status,
                'created_at': request.created_at.isoformat(),
            }

    def get_request_by_cartridge_id(self, cartridge_id: str) -> Optional[Dict]:
        """Получить заявку по коду картриджа"""
        with self.get_session() as session:
            req = session.query(CartridgeRequest).filter(
                CartridgeRequest.cartridge_id == cartridge_id
            ).first()

            if req:
                return {
                    'id': req.id,
                    'cartridge_id': req.cartridge_id,
                    'max_user_id': req.max_user_id,
                    'chat_id': req.chat_id,
                    'fio': req.fio,
                    'cabinet': req.cabinet,
                    'status': req.status,
                    'created_at': req.created_at.isoformat() if req.created_at else None,
                    'received_at': req.received_at.isoformat() if req.received_at else None,
                }
            return None

    def get_pending_requests(self, limit: int = 100) -> List[Dict]:
        """🔥 Получить все заявки со статусом 'pending' (ожидают получения)"""
        with self.get_session() as session:
            requests = session.query(CartridgeRequest).filter(
                CartridgeRequest.status == 'pending'
            ).order_by(CartridgeRequest.created_at).limit(limit).all()

            return [{
                'id': r.id,
                'cartridge_id': r.cartridge_id,
                'fio': r.fio,
                'cabinet': r.cabinet,
                'created_at': r.created_at.isoformat() if r.created_at else None,
            } for r in requests]

    def get_received_requests(self, limit: int = 100) -> List[Dict]:
        """🔥 Получить все заявки со статусом 'received' (готовы к отчёту)"""
        with self.get_session() as session:
            requests = session.query(CartridgeRequest).filter(
                CartridgeRequest.status == 'received'
            ).order_by(CartridgeRequest.received_at).limit(limit).all()

            return [{
                'id': r.id,
                'cartridge_id': r.cartridge_id,
                'fio': r.fio,
                'cabinet': r.cabinet,
                'received_at': r.received_at.isoformat() if r.received_at else None,
            } for r in requests]

    def mark_as_received(self, cartridge_id: str, admin_id: int) -> bool:
        """Отметить картридж как полученный"""
        with self.get_session() as session:
            req = session.query(CartridgeRequest).filter(
                CartridgeRequest.cartridge_id == cartridge_id,
                CartridgeRequest.status == 'pending'
            ).first()

            if req:
                req.status = 'received'
                req.received_at = datetime.utcnow()
                req.received_by_admin_id = admin_id
                req.updated_at = datetime.utcnow()
                logger.info(f"✅ Картридж {cartridge_id} отмечен как полученный")
                return True
            return False

    def cancel_request(self, cartridge_id: str) -> bool:
        """Отменить заявку"""
        with self.get_session() as session:
            req = session.query(CartridgeRequest).filter(
                CartridgeRequest.cartridge_id == cartridge_id,
                CartridgeRequest.status == 'pending'
            ).first()

            if req:
                req.status = 'cancelled'
                req.updated_at = datetime.utcnow()
                logger.info(f"❌ Заявка {cartridge_id} отменена")
                return True
            return False

    def archive_pending_requests(self, report_id: int) -> int:
        """
        Переместить все полученные заявки в архив
        Возвращает количество заархивированных записей
        """
        with self.get_session() as session:
            pending = session.query(CartridgeRequest).filter(
                CartridgeRequest.status == 'received'
            ).all()

            archived_count = 0
            for req in pending:
                archive = CartridgeArchive(
                    cartridge_id=req.cartridge_id,
                    max_user_id=req.max_user_id,
                    fio=req.fio,
                    cabinet=req.cabinet,
                    received_at=req.received_at,
                    received_by_admin_id=req.received_by_admin_id,
                    report_id=report_id,
                    archived_at=datetime.utcnow(),
                )
                session.add(archive)
                session.delete(req)
                archived_count += 1

            logger.info(f"📦 Заархивировано {archived_count} заявок в отчёт #{report_id}")
            return archived_count

    def create_report(self, report_name: str, file_path: str, admin_id: int, count: int) -> Dict:
        """Создать запись о сгенерированном отчёте"""
        with self.get_session() as session:
            report = GeneratedReport(
                report_name=report_name,
                file_path=file_path,
                generated_at=datetime.utcnow(),
                generated_by_admin_id=admin_id,
                cartridges_count=count,
            )
            session.add(report)

            return {
                'id': report.id,
                'report_name': report.report_name,
                'file_path': report.file_path,
                'generated_at': report.generated_at.isoformat(),
                'cartridges_count': report.cartridges_count,
            }

    def get_all_reports(self, limit: int = 50) -> List[Dict]:
        """Получить список всех сгенерированных отчётов"""
        with self.get_session() as session:
            reports = session.query(GeneratedReport).order_by(
                GeneratedReport.generated_at.desc()
            ).limit(limit).all()

            return [{
                'id': r.id,
                'report_name': r.report_name,
                'file_path': r.file_path,
                'generated_at': r.generated_at.isoformat(),
                'cartridges_count': r.cartridges_count,
            } for r in reports]

    def get_report_by_id(self, report_id: int) -> Optional[Dict]:
        """Получить отчёт по ID"""
        with self.get_session() as session:
            report = session.query(GeneratedReport).filter(
                GeneratedReport.id == report_id
            ).first()

            if report:
                return {
                    'id': report.id,
                    'report_name': report.report_name,
                    'file_path': report.file_path,
                    'generated_at': report.generated_at.isoformat(),
                    'cartridges_count': report.cartridges_count,
                }
            return None

    def get_archive_for_report(self, report_id: int) -> List[Dict]:
        """Получить архивные записи для отчёта"""
        with self.get_session() as session:
            records = session.query(CartridgeArchive).filter(
                CartridgeArchive.report_id == report_id
            ).order_by(CartridgeArchive.archived_at).all()

            return [{
                'cartridge_id': r.cartridge_id,
                'fio': r.fio,
                'cabinet': r.cabinet,
                'received_at': r.received_at.isoformat() if r.received_at else None,
            } for r in records]