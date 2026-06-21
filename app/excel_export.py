from __future__ import annotations
from io import BytesIO
from datetime import datetime
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Font


def build_excel_bytes(city_frames: dict[str, pd.DataFrame], date_from: str, date_to: str) -> bytes:
    output = BytesIO()
    all_df = pd.concat(city_frames.values(), ignore_index=True) if city_frames else pd.DataFrame()

    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        readme = pd.DataFrame([
            ['Дата формирования', datetime.now().strftime('%Y-%m-%d %H:%M:%S')],
            ['Период', f'{date_from} — {date_to}'],
            ['Количество городов', len(city_frames)],
            ['Листы', 'README, ALL_DATA, ' + ', '.join(city_frames.keys())],
            ['Важно', 'Это бесплатная stateless-версия под Render Free: файл формируется на лету и должен быть сразу скачан пользователем.'],
        ], columns=['Параметр', 'Значение'])
        readme.to_excel(writer, sheet_name='README', index=False)
        all_df.to_excel(writer, sheet_name='ALL_DATA', index=False)
        for sheet_name, df in city_frames.items():
            df.to_excel(writer, sheet_name=sheet_name[:31], index=False)

    output.seek(0)
    wb = load_workbook(output)
    for ws in wb.worksheets:
        for cell in ws[1]:
            cell.font = Font(bold=True)
    final_output = BytesIO()
    wb.save(final_output)
    final_output.seek(0)
    return final_output.getvalue()
