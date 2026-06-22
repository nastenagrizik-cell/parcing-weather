import csv
import gzip
import io
import logging
import re
from datetime import datetime
from typing import Dict, List, Tuple

import pandas as pd
import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

RP5_BASE = "https://rp5.ru"
SEARCH_URL = f"{RP5_BASE}/search.php"
ARCHIVE_POST_URL = f"{RP5_BASE}/responses/reFileSynop.php"
DOWNLOAD_BASE = RP5_BASE

CANONICAL_COLUMNS = [
    "local_date", "local_time", "datetime_local", "city", "station_name", "wmo_id", "source_url",
    "T", "Po", "P", "Pa", "U", "DD", "Ff", "ff10", "ff3", "N", "WW", "W1", "W2",
    "Tn", "Tx", "Cl", "Nh", "H", "Cm", "Ch", "VV", "Td", "RRR", "tR", "E", "Tg", "Eprime", "sss",
]

HEADER_ALIASES = {
    "Местное время в": "datetime_local",
    "Местное время": "datetime_local",
    "Дата": "local_date",
    "Время": "local_time",
    "T": "T",
    "Po": "Po",
    "P": "P",
    "Pa": "Pa",
    "U": "U",
    "DD": "DD",
    "Ff": "Ff",
    "ff10": "ff10",
    "ff3": "ff3",
    "N": "N",
    "WW": "WW",
    "W1": "W1",
    "W2": "W2",
    "Tn": "Tn",
    "Tx": "Tx",
    "Cl": "Cl",
    "Nh": "Nh",
    "H": "H",
    "Cm": "Cm",
    "Ch": "Ch",
    "VV": "VV",
    "Td": "Td",
    "RRR": "RRR",
    "tR": "tR",
    "E": "E",
    "Tg": "Tg",
    "E'": "Eprime",
    "E’": "Eprime",
    "Eprime": "Eprime",
    "sss": "sss",
}


def sanitize_sheet_name(name: str) -> str:
    bad = r'[:\\/?*\[\]]'
    cleaned = re.sub(bad, '_', name).strip()
    return cleaned[:31] or 'Sheet1'


def _clean_cell(value) -> str:
    if value is None:
        return ''
    text = str(value).replace('\xa0', ' ').strip()
    return '' if text in {'', '-', '—'} else text


def _parse_dt(raw: str) -> Tuple[str, str, str]:
    raw = _clean_cell(raw)
    if not raw:
        return '', '', ''
    txt = re.sub(r'\s+', ' ', raw)
    m = re.search(r'(\d{2}\.\d{2}\.\d{4})\s+(\d{2}:\d{2}|\d{2}:\d{2}:\d{2}|\d{2}:\d{2}:\d{2}|\d{2}:\d{2}|\d{2}:\d{2})', txt)
    if m:
        d, t = m.group(1), m.group(2)[:5]
        dt = datetime.strptime(f'{d} {t}', '%d.%m.%Y %H:%M')
        return dt.strftime('%Y-%m-%d'), dt.strftime('%H%M'), dt.strftime('%Y-%m-%d %H%M')
    m2 = re.search(r'(\d{2}\.\d{2}\.\d{4})\s+(\d{2}:\d{2})', txt)
    if m2:
        d, t = m2.group(1), m2.group(2)
        dt = datetime.strptime(f'{d} {t}', '%d.%m.%Y %H:%M')
        return dt.strftime('%Y-%m-%d'), dt.strftime('%H%M'), dt.strftime('%Y-%m-%d %H%M')
    return '', '', txt


def _find_station_candidates(city_name: str) -> List[Dict[str, str]]:
    resp = requests.get(SEARCH_URL, params={'name': city_name}, timeout=30)
    resp.raise_for_status()
    html = resp.text
    links = re.findall(r'href="([^"]*(?:Архив_погоды|Weather_archive)[^"]*)"[^>]*>([^<]+)</a>', html, flags=re.I)
    candidates = []
    for href, title in links:
        url = href if href.startswith('http') else RP5_BASE + href
        wmo = None
        m = re.search(r'[?&]wmo_id=(\d+)', url)
        if m:
            wmo = m.group(1)
        candidates.append({'station_name': BeautifulSoup(title, 'html.parser').get_text(' ', strip=True), 'url': url, 'wmo_id': wmo or ''})
    return candidates


def resolve_station(city_name: str) -> Dict[str, str]:
    candidates = _find_station_candidates(city_name)
    if not candidates:
        raise ValueError(f'Не удалось найти станцию RP5 для города: {city_name}')
    best = candidates[0]
    page = requests.get(best['url'], timeout=30)
    page.raise_for_status()
    page.encoding = page.apparent_encoding or page.encoding
    m = re.search(r'wmo_id=(\d+)', page.text)
    if m:
        best['wmo_id'] = m.group(1)
    if not best['wmo_id']:
        m2 = re.search(r'"wmo_id"\s*:?\s*"?(\d+)"?', page.text)
        if m2:
            best['wmo_id'] = m2.group(1)
    if not best['wmo_id']:
        raise ValueError(f'Не удалось определить wmo_id для {city_name}')
    return best


def _extract_download_url(html: str) -> str:
    m = re.search(r'href=["\']([^"\']+\.csv(?:\.gz)?[^"\']*)["\']', html, flags=re.I)
    if not m:
        m = re.search(r'(?:https?:)?//[^\s"\']+\.csv(?:\.gz)?', html, flags=re.I)
    if not m:
        raise ValueError('Не найдена ссылка на CSV/GZ архив RP5')
    url = m.group(1)
    if url.startswith('//'):
        url = 'https:' + url
    elif url.startswith('/'):
        url = DOWNLOAD_BASE + url
    elif not url.startswith('http'):
        url = DOWNLOAD_BASE + '/' + url.lstrip('/')
    return url


def _download_archive(station: Dict[str, str], date_from: str, date_to: str) -> bytes:
    d1 = datetime.strptime(date_from, '%Y-%m-%d').strftime('%d.%m.%Y')
    d2 = datetime.strptime(date_to, '%Y-%m-%d').strftime('%d.%m.%Y')
    session = requests.Session()
    station_page = session.get(station['url'], timeout=30)
    station_page.raise_for_status()
    payload = {
        'wmo_id': station['wmo_id'],
        'a_date1': d1,
        'a_date2': d2,
        'f_ed3': '6',
        'f_ed4': '6',
        'f_ed5': '22',
        'f_pe': '1',
        'f_pe1': '2',
        'lng_id': '2',
        'type': 'csv',
    }
    resp = session.post(ARCHIVE_POST_URL, data=payload, timeout=90)
    resp.raise_for_status()
    download_url = _extract_download_url(resp.text)
    file_resp = session.get(download_url, timeout=120)
    file_resp.raise_for_status()
    return file_resp.content


def _decode_archive(content: bytes) -> str:
    if content[:2] == b'\x1f\x8b':
        return gzip.decompress(content).decode('utf-8-sig', errors='replace')
    for enc in ('utf-8-sig', 'utf-8', 'cp1251', 'latin1'):
        try:
            return content.decode(enc)
        except Exception:
            continue
    return content.decode('utf-8', errors='replace')


def _normalize_header(raw_headers: List[str]) -> List[str]:
    result = []
    for col in raw_headers:
        col = _clean_cell(col)
        col = re.sub(r'\s+', ' ', col)
        mapped = HEADER_ALIASES.get(col)
        if mapped is None:
            for k, v in HEADER_ALIASES.items():
                if col.startswith(k):
                    mapped = v
                    break
        result.append(mapped or col)
    return result


def _read_rp5_csv(text: str) -> pd.DataFrame:
    lines = [line for line in text.splitlines() if line.strip()]
    header_idx = None
    for i, line in enumerate(lines[:20]):
        if 'Местное время' in line and ('T' in line or ';T;' in line or ',T,' in line):
            header_idx = i
            break
    if header_idx is None:
        raise ValueError('Не удалось найти строку заголовков в архиве RP5')
    sample = lines[header_idx]
    delimiter = ';' if sample.count(';') >= sample.count(',') else ','
    csv_text = '\n'.join(lines[header_idx:])
    df = pd.read_csv(io.StringIO(csv_text), sep=delimiter, dtype=str, engine='python')
    df.columns = _normalize_header(list(df.columns))
    return df


def fetch_city_weather(city_name: str, date_from: str, date_to: str) -> pd.DataFrame:
    station = resolve_station(city_name)
    content = _download_archive(station, date_from, date_to)
    text = _decode_archive(content)
    raw = _read_rp5_csv(text)

    out = pd.DataFrame(columns=CANONICAL_COLUMNS)
    for col in raw.columns:
        if col in out.columns:
            out[col] = raw[col].map(_clean_cell)

    if 'datetime_local' in raw.columns:
        parsed = raw['datetime_local'].map(_parse_dt)
        out['local_date'] = [p[0] for p in parsed]
        out['local_time'] = [p[1] for p in parsed]
        out['datetime_local'] = [p[2] for p in parsed]

    if 'local_date' in raw.columns and raw['local_date'].notna().any():
        out['local_date'] = raw['local_date'].map(_clean_cell)
    if 'local_time' in raw.columns and raw['local_time'].notna().any():
        out['local_time'] = raw['local_time'].map(_clean_cell)

    out['city'] = city_name
    out['station_name'] = station['station_name']
    out['wmo_id'] = station['wmo_id']
    out['source_url'] = station['url']

    for col in CANONICAL_COLUMNS:
        if col not in out.columns:
            out[col] = ''

    out = out[CANONICAL_COLUMNS].fillna('')
    out = out[out['datetime_local'].astype(str).str.strip() != '']
    return out.reset_index(drop=True)
