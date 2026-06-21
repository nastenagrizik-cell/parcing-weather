import os
from datetime import datetime
from fastapi import FastAPI, Request, Form, Depends, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from .db import SessionLocal, engine, Base
from .models import City, RunLog
from .parser import fetch_city_weather, sanitize_sheet_name
from .excel_export import build_excel

app = FastAPI(title='Погодный архив RP5')
app.mount('/static', StaticFiles(directory='app/static'), name='static')
templates = Jinja2Templates(directory='app/templates')
DATA_DIR = os.getenv('DATA_DIR', 'data')
EXPORT_DIR = os.path.join(DATA_DIR, 'exports')
os.makedirs(EXPORT_DIR, exist_ok=True)
Base.metadata.create_all(bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def run_export_task(run_id: int, date_from: str, date_to: str):
    db = SessionLocal()
    run = None
    try:
        run = db.query(RunLog).filter(RunLog.id == run_id).first()
        cities = db.query(City).filter(City.is_active == True).order_by(City.name).all()
        frames = {}
        messages = []
        for city in cities:
            try:
                frames[city.sheet_name] = fetch_city_weather(city.name, city.rp5_url, date_from, date_to)
                messages.append(f'OK: {city.name} -> {city.sheet_name}')
            except Exception as e:
                messages.append(f'ERROR: {city.name} — {e}')
        output_file = build_excel(frames, EXPORT_DIR, date_from, date_to)
        run.status = 'done'
        run.finished_at = datetime.now()
        run.output_file = output_file
        run.message = '\n'.join(messages)
        db.commit()
    except Exception as e:
        if run:
            run.status = 'error'
            run.finished_at = datetime.now()
            run.message = str(e)
            db.commit()
    finally:
        db.close()


@app.get('/', response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    cities = db.query(City).order_by(City.name).all()
    last_run = db.query(RunLog).order_by(RunLog.id.desc()).first()
    return templates.TemplateResponse('index.html', {'request': request, 'cities': cities, 'last_run': last_run})


@app.post('/cities/add')
def add_city(name: str = Form(...), rp5_url: str = Form(...), is_active: str | None = Form(None), db: Session = Depends(get_db)):
    clean_name = name.strip()
    city = City(name=clean_name, rp5_url=rp5_url.strip(), sheet_name=sanitize_sheet_name(clean_name), is_active=bool(is_active))
    db.add(city)
    db.commit()
    return RedirectResponse('/', status_code=303)


@app.post('/cities/bulk-add')
def bulk_add_cities(cities_text: str = Form(...), db: Session = Depends(get_db)):
    lines = [line.strip() for line in cities_text.splitlines() if line.strip()]
    added = 0
    for line in lines:
        parts = [p.strip() for p in line.split('|', 1)]
        name = parts[0]
        url = parts[1] if len(parts) > 1 else ''
        if not name or not url:
            continue
        city = City(name=name, rp5_url=url, sheet_name=sanitize_sheet_name(name), is_active=True)
        db.add(city)
        added += 1
    if added:
        db.commit()
    return RedirectResponse('/', status_code=303)


@app.post('/cities/{city_id}/delete')
def delete_city(city_id: int, db: Session = Depends(get_db)):
    city = db.query(City).filter(City.id == city_id).first()
    if city:
        db.delete(city)
        db.commit()
    return RedirectResponse('/', status_code=303)


@app.post('/export/run')
def run_export(background_tasks: BackgroundTasks, date_from: str = Form(...), date_to: str = Form(...), db: Session = Depends(get_db)):
    run = RunLog(status='running', started_at=datetime.now(), message='Запуск выгрузки')
    db.add(run)
    db.commit()
    db.refresh(run)
    background_tasks.add_task(run_export_task, run.id, date_from, date_to)
    return RedirectResponse('/', status_code=303)


@app.get('/export/latest')
def download_latest(db: Session = Depends(get_db)):
    last_run = db.query(RunLog).order_by(RunLog.id.desc()).first()
    if not last_run or not last_run.output_file or not os.path.exists(last_run.output_file):
        return RedirectResponse('/', status_code=303)
    return FileResponse(last_run.output_file, filename=os.path.basename(last_run.output_file))
