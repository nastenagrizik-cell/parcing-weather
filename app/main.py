from __future__ import annotations
from io import StringIO
from datetime import datetime
import csv
from fastapi import FastAPI, Request, UploadFile, File, Form, HTTPException
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from .parser import fetch_city_weather
from .excel_export import build_excel_bytes

app = FastAPI(title='RP5 Weather Export Final')
app.mount('/static', StaticFiles(directory='app/static'), name='static')
templates = Jinja2Templates(directory='app/templates')


def normalize_sheet_name(value: str) -> str:
    banned = '[]:*?/\\'
    cleaned = ''.join('_' if ch in banned else ch for ch in value).strip()
    return (cleaned or 'Sheet')[:31]


@app.get('/', response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse('index.html', {'request': request})


@app.post('/export')
async def export_weather(
    request: Request,
    date_from: str = Form(...),
    date_to: str = Form(...),
    cities_file: UploadFile = File(...),
):
    if not cities_file.filename.lower().endswith('.csv'):
        raise HTTPException(status_code=400, detail='Нужен CSV-файл со списком городов.')

    content = await cities_file.read()
    try:
        text = content.decode('utf-8-sig')
    except UnicodeDecodeError:
        text = content.decode('cp1251')

    reader = csv.DictReader(StringIO(text))
    required = {'name', 'sheet_name'}
    if not reader.fieldnames or not required.issubset(set(reader.fieldnames)):
        raise HTTPException(status_code=400, detail='CSV должен содержать колонки: name, sheet_name')

    city_frames = {}
    processed = 0
    for row in reader:
        name = (row.get('name') or '').strip()
        sheet_name = normalize_sheet_name((row.get('sheet_name') or name).strip())
        if not name:
            continue
        city_frames[sheet_name] = fetch_city_weather(name, date_from, date_to)
        processed += 1

    if processed == 0:
        raise HTTPException(status_code=400, detail='В CSV нет валидных строк для обработки.')

    excel_bytes = build_excel_bytes(city_frames, date_from, date_to)
    filename = f"weather_export_{datetime.now().strftime('%Y%m%d_%H%M%S')}.xlsx"
    headers = {'Content-Disposition': f'attachment; filename={filename}'}
    return StreamingResponse(
        iter([excel_bytes]),
        media_type='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        headers=headers,
    )
