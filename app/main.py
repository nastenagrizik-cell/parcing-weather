import os
import logging
import traceback
from datetime import datetime

from fastapi import FastAPI, Request, Form, Depends, BackgroundTasks
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from .db import SessionLocal, engine, Base
from .models import City, RunLog
from .parser import fetch_city_weather, sanitize_sheet_name, resolve_station
from .excel_export import build_excel


logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


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


@app.head("/", response_class=PlainTextResponse)
def head_index():
    return PlainTextResponse("ok", status_code=200)


def run_export_task(run_id: int, date_from: str, date_to: str):
    db = SessionLocal()
    run = None

    logger.info("START export task: run_id=%s, date_from=%s, date_to=%s", run_id, date_from, date_to)

    try:
        run = db.query(RunLog).filter(RunLog.id == run_id).first()
        cities = db.query(City).filter(City.is_active == True).order_by(City.name).all()

        logger.info("ACTIVE cities count: %s", len(cities))

        frames = {}
        messages = []

        for city in cities:
            logger.info("PROCESS city: %s", city.name)

            try:
                station = resolve_station(city.name)
                logger.info("RESOLVED station for %s: %s", city.name, station)

                sheet_name = city.sheet_name or sanitize_sheet_name(city.name)
                frame = fetch_city_weather(city.name, date_from, date_to)

                logger.info("FETCHED rows for %s: %s", city.name, len(frame))

                frames[sheet_name] = frame
                messages.append(f"OK: {city.name} -> {station['station_name']} -> {sheet_name}")

            except Exception as e:
                err_text = f"ERROR: {city.name} — {e}"
                logger.exception("FAILED city: %s", city.name)
                messages.append(err_text)

        logger.info("SUCCESS frames count: %s", len(frames))

        output_file = build_excel(
            city_frames=frames,
            output_dir=EXPORT_DIR,
            date_from=date_from,
            date_to=date_to,
            messages=messages,
        )

        logger.info("EXCEL built: %s", output_file)

        run.status = 'done'
        run.finished_at = datetime.now()
        run.output_file = output_file
        run.message = '\n'.join(messages) if messages else 'Выгрузка завершена'
        db.commit()

        logger.info("RUN completed: run_id=%s", run_id)

    except Exception as e:
        logger.exception("FATAL export task error: run_id=%s", run_id)

        if run:
            run.status = 'error'
            run.finished_at = datetime.now()
            run.message = f"{e}\n\n{traceback.format_exc()}"
            db.commit()
    finally:
        db.close()


@app.get('/', response_class=HTMLResponse)
def index(request: Request, db: Session = Depends(get_db)):
    cities = db.query(City).order_by(City.name).all()
    last_run = db.query(RunLog).order_by(RunLog.id.desc()).first()
    return templates.TemplateResponse(
        'index.html',
        {
            'request': request,
            'cities': cities,
            'last_run': last_run
        }
    )


@app.post('/cities/add')
def add_city(
    name: str = Form(...),
    is_active: str | None = Form(None),
    db: Session = Depends(get_db)
):
    clean_name = name.strip()

    existing = db.query(City).filter(City.name == clean_name).first()
    if existing:
        return RedirectResponse('/', status_code=303)

    city = City(
        name=clean_name,
        rp5_url='auto',
        sheet_name=sanitize_sheet_name(clean_name),
        is_active=bool(is_active),
    )
    db.add(city)
    db.commit()
    return RedirectResponse('/', status_code=303)


@app.post('/cities/bulk-add')
def bulk_add_cities(cities_text: str = Form(...), db: Session = Depends(get_db)):
    lines = [line.strip() for line in cities_text.splitlines() if line.strip()]
    added = 0

    for line in lines:
        name = line.strip()
        if not name:
            continue

        existing = db.query(City).filter(City.name == name).first()
        if existing:
            continue

        city = City(
            name=name,
            rp5_url='auto',
            sheet_name=sanitize_sheet_name(name),
            is_active=True,
        )
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
def run_export(
    background_tasks: BackgroundTasks,
    date_from: str = Form(...),
    date_to: str = Form(...),
    db: Session = Depends(get_db)
):
    run = RunLog(
        status='running',
        started_at=datetime.now(),
        message='Запуск выгрузки'
    )
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
