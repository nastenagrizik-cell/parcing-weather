from __future__ import annotations
from datetime import datetime
from urllib.parse import quote
import re
import pandas as pd
import httpx
from bs4 import BeautifulSoup
from weather_rp5 import get_station_id, get_weather_data

SEARCH_URL = 'https://rp5.ru/search.php?name={query}'
HEADERS = {'User-Agent': 'Mozilla/5.0'}


def normalize_city_name(name: str) -> str:
    name = re.sub(r'\s+', ' ', name.strip())
    return name.replace('ё', 'е').replace('Ё', 'Е')


def translit_like(value: str) -> str:
    mapping = {
        'а':'a','б':'b','в':'v','г':'g','д':'d','е':'e','ё':'e','ж':'zh','з':'z','и':'i','й':'y','к':'k','л':'l','м':'m','н':'n','о':'o','п':'p','р':'r','с':'s','т':'t','у':'u','ф':'f','х':'h','ц':'ts','ч':'ch','ш':'sh','щ':'sch','ы':'y','э':'e','ю':'yu','я':'ya','ь':'','ъ':'',
    }
    out = []
    for ch in value.lower():
        out.append(mapping.get(ch, ch))
    return ''.join(out)


def score_candidate(city: str, title: str, url: str) -> int:
    score = 0
    c = city.lower()
    t = title.lower()
    if c == t:
        score += 100
    if c in t:
        score += 60
    if 'weather archive' in t or 'архив погоды' in t:
        score += 20
    if 'airport' in t or 'аэропорт' in t:
        score -= 25
    if 'metar' in t:
        score -= 25
    if 'район' in t or 'street' in t or 'проезд' in t or 'улиц' in t:
        score -= 40
    if url.startswith('http://rp5.ru/archive.php') or '/Weather_archive' in url or '/Архив_погоды_' in url:
        score += 25
    return score


def candidate_from_direct_archive(city_name: str) -> dict:
    translit = translit_like(city_name).replace(' ', '_')
    return {
        'title': f'Weather archive in {city_name}',
        'url': f'https://rp5.ru/Weather_archive_in_{translit}',
        'source': 'direct-pattern',
    }


def search_rp5_candidates(city_name: str) -> list[dict]:
    city = normalize_city_name(city_name)
    candidates = [candidate_from_direct_archive(city)]
    query = quote(city)
    url = SEARCH_URL.format(query=query)
    try:
        r = httpx.get(url, headers=HEADERS, timeout=20, follow_redirects=True)
        final_url = str(r.url)
        title = ''
        soup = BeautifulSoup(r.text, 'lxml')
        if soup.title:
            title = soup.title.get_text(' ', strip=True)
        if final_url != url:
            candidates.append({'title': title or city, 'url': final_url, 'source': 'search-redirect'})
        for a in soup.find_all('a', href=True):
            href = a['href']
            text = a.get_text(' ', strip=True)
            if 'archive.php?wmo_id=' in href or 'Weather_archive' in href or 'Архив_погоды_' in href:
                full = href if href.startswith('http') else 'https://rp5.ru' + href
                candidates.append({'title': text or full, 'url': full, 'source': 'search-page'})
    except Exception:
        pass

    uniq = []
    seen = set()
    for cand in candidates:
        key = cand['url']
        if key not in seen:
            seen.add(key)
            uniq.append(cand)
    return uniq


def pick_best_candidate(city_name: str, candidates: list[dict]) -> dict:
    if not candidates:
        return {
            'query': city_name,
            'matched_station': '',
            'rp5_url': '',
            'match_status': 'not_found',
            'match_score': 0,
            'match_reason': 'Кандидаты не найдены',
        }

    scored = []
    for cand in candidates:
        score = score_candidate(city_name, cand.get('title', ''), cand.get('url', ''))
        scored.append({**cand, 'score': score})
    scored.sort(key=lambda x: x['score'], reverse=True)
    best = scored[0]
    second = scored[1] if len(scored) > 1 else None

    status = 'matched'
    reason = 'Выбран лучший кандидат по score'
    if best['score'] < 40:
        status = 'ambiguous'
        reason = 'Низкая уверенность в совпадении'
    if second and best['score'] - second['score'] < 10:
        status = 'ambiguous'
        reason = 'Есть несколько похожих кандидатов'

    return {
        'query': city_name,
        'matched_station': best.get('title', ''),
        'rp5_url': best.get('url', ''),
        'match_status': status,
        'match_score': best.get('score', 0),
        'match_reason': reason,
    }


def search_city_on_rp5(city_name: str) -> dict:
    candidates = search_rp5_candidates(city_name)
    return pick_best_candidate(city_name, candidates)


def fetch_city_weather(city_name: str, date_from: str, date_to: str) -> pd.DataFrame:
    station = search_city_on_rp5(city_name)
    if station['match_status'] != 'matched' or not station['rp5_url']:
        return pd.DataFrame([
            {
                'city': city_name,
                'matched_station': station['matched_station'],
                'rp5_url': station['rp5_url'],
                'match_status': station['match_status'],
                'match_score': station['match_score'],
                'match_reason': station['match_reason'],
                'date_from': date_from,
                'date_to': date_to,
                'loaded_at': datetime.utcnow().isoformat(timespec='seconds'),
                'error': 'Станция не найдена уверенно, архив не скачан.'
            }
        ])

    try:
        station_id = get_station_id(station['rp5_url'])
        start = pd.to_datetime(date_from).date()
        end = pd.to_datetime(date_to).date()
        df = get_weather_data(station_id, start, end, False)
        if not isinstance(df, pd.DataFrame):
            df = pd.DataFrame(df)
        df.insert(0, 'city', city_name)
        df.insert(1, 'matched_station', station['matched_station'])
        df.insert(2, 'rp5_url', station['rp5_url'])
        df.insert(3, 'match_status', station['match_status'])
        df.insert(4, 'match_score', station['match_score'])
        df.insert(5, 'match_reason', station['match_reason'])
        return df
    except Exception as e:
        return pd.DataFrame([
            {
                'city': city_name,
                'matched_station': station['matched_station'],
                'rp5_url': station['rp5_url'],
                'match_status': 'error',
                'match_score': station['match_score'],
                'match_reason': station['match_reason'],
                'date_from': date_from,
                'date_to': date_to,
                'loaded_at': datetime.utcnow().isoformat(timespec='seconds'),
                'error': str(e)
            }
        ])
