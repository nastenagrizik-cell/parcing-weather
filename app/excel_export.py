from datetime import datetime
from pathlib import Path
from typing import Dict, List

import pandas as pd
from openpyxl.utils import get_column_letter

CANONICAL_COLUMNS = [
    "local_date", "local_time", "datetime_local", "city", "station_name", "wmo_id", "source_url",
    "T", "Po", "P", "Pa", "U", "DD", "Ff", "ff10", "ff3", "N", "WW", "W1", "W2",
    "Tn", "Tx", "Cl", "Nh", "H", "Cm", "Ch", "VV", "Td", "RRR", "tR", "E", "Tg", "Eprime", "sss",
]


def build_excel(city_frames: Dict[str, pd.DataFrame], output_dir: str, date_from: str, date_to: str, messages: List[str]) -> str:
    Path(output_dir).mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
    out_path = Path(output_dir) / f'arhiv_pogody_{date_from}_{date_to}_{ts}.xlsx'

    all_frames = []
    for sheet_name, df in city_frames.items():
        copy_df = df.copy()
        for col in CANONICAL_COLUMNS:
            if col not in copy_df.columns:
                copy_df[col] = ''
        all_frames.append(copy_df[CANONICAL_COLUMNS])

    with pd.ExcelWriter(out_path, engine='openpyxl') as writer:
        readme = pd.DataFrame({
            'item': ['generated_at', 'date_from', 'date_to', 'cities', 'notes'],
            'value': [datetime.now().strftime('%Y-%m-%d %H:%M:%S'), date_from, date_to, len(city_frames), 'Полная выгрузка RP5 через CSV/GZ архив']
        })
        readme.to_excel(writer, sheet_name='README', index=False)

        if all_frames:
            alldf = pd.concat(all_frames, ignore_index=True)
        else:
            alldf = pd.DataFrame(columns=CANONICAL_COLUMNS)
        alldf.to_excel(writer, sheet_name='ALLDATA', index=False)

        colmap = pd.DataFrame({'column_name': CANONICAL_COLUMNS})
        colmap.to_excel(writer, sheet_name='COLUMNSMAP', index=False)

        for sheet_name, df in city_frames.items():
            export_df = df.copy()
            for col in CANONICAL_COLUMNS:
                if col not in export_df.columns:
                    export_df[col] = ''
            export_df = export_df[CANONICAL_COLUMNS]
            export_df.to_excel(writer, sheet_name=sheet_name[:31], index=False)

        wb = writer.book
        for ws in wb.worksheets:
            for idx, col in enumerate(ws.columns, start=1):
                width = max(len(str(c.value or '')) for c in col[:200]) if col else 12
                ws.column_dimensions[get_column_letter(idx)].width = min(max(width + 2, 12), 28)
            ws.freeze_panes = 'A2'

    return str(out_path)
