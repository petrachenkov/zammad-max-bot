"""
Генерация Excel-файлов для заявок на заправку картриджей
"""

import logging
import os
from datetime import datetime
from typing import List, Dict

try:
    import xlsxwriter
    EXCEL_AVAILABLE = True
except ImportError:
    EXCEL_AVAILABLE = False
    logger = logging.getLogger(__name__)
    logger.warning("⚠️ xlsxwriter не установлен. Установите: pip install xlsxwriter")

logger = logging.getLogger(__name__)


def generate_cartridge_excel(
    requests: List[Dict],
    output_dir: str = "reports",
    filename_prefix: str = "cartridges"
) -> str:
    if not EXCEL_AVAILABLE:
        raise ImportError("xlsxwriter не установлен. Установите: pip install xlsxwriter")

    os.makedirs(output_dir, exist_ok=True)

    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M")
    filename = f"{filename_prefix}_{timestamp}.xlsx"
    filepath = os.path.join(output_dir, filename)

    # Создаем книгу
    workbook = xlsxwriter.Workbook(filepath)
    worksheet = workbook.add_worksheet("Картриджи")

    # 🔥 Форматы
    header_format = workbook.add_format({
        'bold': True,
        'align': 'center',
        'valign': 'vcenter',
        'bg_color': '#D9E1F2',
        'border': 2,  # Толстая граница
        'font_size': 12
    })

    cell_format = workbook.add_format({
        'align': 'center',
        'valign': 'vcenter',
        'border': 2  # Толстая граница
    })

    headers = ["И. Фамилия", "Кабинет", "ID картриджа", "Подпись"]

    # Заголовки
    for col, header in enumerate(headers):
        worksheet.write(0, col, header, header_format)

    # Данные
    for row_idx, req in enumerate(requests, start=1):
        fio = req.get('fio', '')
        fio_parts = fio.strip().split()
        if len(fio_parts) >= 3:
            formatted_fio = f"{fio_parts[0][0]}.{fio_parts[1][0]}. {fio_parts[2]}"
        elif len(fio_parts) == 2:
            formatted_fio = f"{fio_parts[0][0]}. {fio_parts[1]}"
        else:
            formatted_fio = fio

        worksheet.write(row_idx, 0, formatted_fio, cell_format)
        worksheet.write(row_idx, 1, req.get('cabinet', ''), cell_format)
        worksheet.write(row_idx, 2, req.get('cartridge_id', ''), cell_format)
        worksheet.write(row_idx, 3, '', cell_format)

    # Ширина столбцов
    worksheet.set_column('A:A', 35)
    worksheet.set_column('B:B', 12)
    worksheet.set_column('C:C', 15)
    worksheet.set_column('D:D', 20)

    # Высота строк
    worksheet.set_row(0, 25)
    for row_idx in range(1, len(requests) + 1):
        worksheet.set_row(row_idx, 20)

    workbook.close()

    logger.info(f"✅ Excel-файл сгенерирован: {filepath} ({len(requests)} записей)")
    return filepath