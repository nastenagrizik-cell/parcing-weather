import os
from datetime import datetime
import pandas as pd
from openpyxl import load_workbook
from openpyxl.styles import Font
from .parser import RP5_CANONICAL_COLUMNS, translit_filename


def _normalize_frame(df: pd.DataFrame) -> pd.DataFrame:
    frame = df.copy()
    for col in RP5_CANONICAL_COLUMNS:
        if col not in frame.columns:
            frame[col] = None
    ordered = frame[RP5_CANONICAL_COLUMNS]
    return ordered


def build_excel(city_frames: dict, output_dir: str, date_from: str, date_to: str) -> str:
    os.makedirs(output_dir, exist_ok=True)
    pretty_name = f'Архив_погоды_{date_from}_{date_to}.xlsx'
    path = os.path.join(output_dir, translit_filename(pretty_name))

    normalized_frames = {sheet: _normalize_frame(df) for sheet, df in city_frames.items()}
    all_df = pd.concat(normalized_frames.values(), ignore_index=True) if normalized_frames else pd.DataFrame(columns=RP5_CANONICAL_COLUMNS)
    columns_map = pd.DataFrame([
        ['local_date', 'Локальная дата'],
        ['local_time', 'Локальное время'],
        ['datetime_local', 'Дата и время'],
        ['city', 'Город из формы'],
        ['station_name', 'Название станции'],
        ['wmo_id', 'WMO ID'],
        ['source_url', 'URL станции на RP5'],
        ['T', 'Температура воздуха'],
        ['Po', 'Атмосферное давление на уровне станции'],
        ['P', 'Атмосферное давление на уровне моря'],
        ['Pa', 'Барическая тенденция'],
        ['U', 'Относительная влажность'],
        ['DD', 'Направление ветра'],
        ['Ff', 'Скорость ветра'],
        ['ff10', 'Порывы за 10 минут'],
        ['ff3', 'Порывы за 3 часа'],
        ['N', 'Облачность'],
        ['WW', 'Текущая погода'],
        ['W1', 'Погода за прошлый срок'],
        ['W2', 'Погода за предпрошлый срок'],
        ['Tn', 'Минимальная температура'],
        ['Tx', 'Максимальная температура'],
        ['Cl', 'Облака нижнего яруса'],
        ['Nh', 'Количество облаков нижнего яруса'],
        ['H', 'Высота нижней границы облаков'],
        ['Cm', 'Облака среднего яруса'],
        ['Ch', 'Облака верхнего яруса'],
        ['VV', 'Горизонтальная видимость'],
        ['Td', 'Точка росы'],
        ['RRR', 'Количество осадков'],
        ['tR', 'Период осадков'],
        ['E', 'Состояние поверхности почвы'],
        ['Tg', 'Температура поверхности почвы'],
        ['E_prime', 'Состояние снежного покрова/почвы'],
        ['sss', 'Высота снежного покрова'],
    ], columns=['column_name', 'description'])

    with pd.ExcelWriter(path, engine='openpyxl') as writer:
        readme = pd.DataFrame([
            ['Файл', pretty_name],
            ['Создан', datetime.now().strftime('%Y-%m-%d %H:%M:%S')],
            ['Период', f'{date_from} — {date_to}'],
            ['Городов', len(normalized_frames)],
            ['Листы', 'README, ALL_DATA, COLUMNS_MAP, ' + ', '.join(normalized_frames.keys())],
            ['Принцип выравнивания', 'Все городские данные приводятся к единой схеме колонок, чтобы значения не сдвигались на общем листе.'],
            ['Примечание', 'В этой версии загрузчик RP5 остается MVP-заглушкой, но структура входа и Excel уже подготовлена под реальные неоднородные выгрузки.'],
        ], columns=['Параметр', 'Значение'])
        readme.to_excel(writer, sheet_name='README', index=False)
        all_df.to_excel(writer, sheet_name='ALL_DATA', index=False)
        columns_map.to_excel(writer, sheet_name='COLUMNS_MAP', index=False)
        for sheet_name, df in normalized_frames.items():
            df.to_excel(writer, sheet_name=sheet_name[:31], index=False)

    wb = load_workbook(path)
    for ws in wb.worksheets:
        for cell in ws[1]:
            cell.font = Font(bold=True)
    wb.save(path)
    return path
