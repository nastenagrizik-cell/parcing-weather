from __future__ import annotations

import re
import unicodedata
from datetime import date
import pandas as pd

from weather_rp5 import get_station_id, get_weather_data


RP5_CANONICAL_COLUMNS = [
    "local_date", "local_time", "datetime_local", "city", "station_name", "wmo_id", "source_url",
    "T", "Po", "P", "Pa", "U", "DD", "Ff", "ff10", "ff3", "N", "WW", "W1", "W2",
    "Tn", "Tx", "Cl", "Nh", "H", "Cm", "Ch", "VV", "Td", "RRR", "tR", "E", "Tg", "E_prime", "sss",
]

COLUMN_ALIASES = {
    "E'": "E_prime",
    "E_prime": "E_prime",

    "date_time": "datetime",
    "Date_Time": "datetime",
    "timestamp": "datetime",
    "time": "datetime",

    "temp": "T",
    "temperature": "T",
    "temp_c": "T",

    "hum": "U",
    "humidity": "U",

    "pressure": "Po",
    "press": "Po",

    "wind_dir": "DD",
    "wind_direction": "DD",

    "wind_speed": "Ff",
    "windspeed": "Ff",

    "cloud": "N",
    "clouds": "N",

    "weather": "WW",
    "weather_desc": "WW",

    "dew_point": "Td",
    "dewpoint": "Td",

    "precipitation": "RRR",
    "precip": "RRR",
}


CITY_STATIONS = {
    "москва": {
        "station_name": "Москва (ВДНХ)",
        "rp5_url": "https://rp5.ru/Архив_погоды_в_Москве_(ВДНХ)",
    },
    "санкт-петербург": {
        "station_name": "Saint Petersburg",
        "rp5_url": "https://rp5.ru/Weather_archive_in_Saint_Petersburg",
    },
    "петербург": {
        "station_name": "Saint Petersburg",
        "rp5_url": "https://rp5.ru/Weather_archive_in_Saint_Petersburg",
    },
    "владивосток": {
        "station_name": "Владивосток",
        "rp5_url": "https://rp5.ru/Архив_погоды_во_Владивостоке",
    },
    "игра": {
        "station_name": "Игра",
        "rp5_url": "https://rp5.in/Архив_погоды_в_Игре",
    },
}


def sanitize_sheet_name(name: str) -> str:
    value = (name or "").strip()
    value = re.sub(r"^Метеостанция\s+", "", value, flags=re.I)
    value = value.replace("'", "")
    value = value.replace("(", " ").replace(")", " ")
    value = value.replace("/", " ")
    value = re.sub(r"[:\\/*?\[\]]+", " ", value)
    value = re.sub(r"\s+", "_", value).strip(" _")
    if not value:
        value = "Город"
    return value[:31]


def translit_filename(value: str) -> str:
    table = {
        "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e", "ж": "zh", "з": "z",
        "и": "i", "й": "y", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "п": "p", "р": "r",
        "с": "s", "т": "t", "у": "u", "ф": "f", "х": "h", "ц": "ts", "ч": "ch", "ш": "sh",
        "щ": "sch", "ъ": "", "ы": "y", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    }
    s = []
    for ch in value.lower():
        s.append(table.get(ch, ch))
    out = "".join(s)
    out = unicodedata.normalize("NFKD", out).encode("ascii", "ignore").decode("ascii")
    out = re.sub(r"[^a-z0-9._-]+", "_", out).strip("._-")
    return out or "export"


def normalize_city_key(city_name: str) -> str:
    value = (city_name or "").strip().lower()
    value = value.replace("ё", "е")
    value = re.sub(r"\s+", " ", value)
    return value


def resolve_station(city_name: str) -> dict:
    key = normalize_city_key(city_name)
    station = CITY_STATIONS.get(key)
    if not station:
        available = ", ".join(sorted(CITY_STATIONS.keys()))
        raise ValueError(
            f"Для города '{city_name}' станция пока не настроена. "
            f"Добавь город в CITY_STATIONS. Сейчас доступны: {available}"
        )
    return station


def extract_station_name(city_name: str, rp5_url: str, fallback_station_name: str | None = None) -> str:
    if fallback_station_name:
        return fallback_station_name

    slug = rp5_url.rsplit("/", 1)[-1]
    slug = re.sub(r"^Архив_погоды_в_", "", slug)
    slug = re.sub(r"^Архив_погоды_во_", "", slug)
    slug = re.sub(r"^Weather_archive_in_", "", slug)
    slug = slug.replace("_", " ")
    slug = re.sub(r"%[0-9A-Fa-f]{2}", " ", slug)
    slug = re.sub(r"\s+", " ", slug).strip(" ()")
    return city_name if city_name else (slug or "Неизвестная станция")


def _find_datetime_column(frame: pd.DataFrame) -> str | None:
    candidates = ["datetime", "date_time", "date", "timestamp", "time"]
    lower_map = {str(col).strip().lower(): col for col in frame.columns}

    for candidate in candidates:
        if candidate.lower() in lower_map:
            return lower_map[candidate.lower()]
    return None


def _normalize_weather_rp5_frame(
    df: pd.DataFrame,
    city_name: str,
    rp5_url: str,
    wmo_id: str | None,
    station_name: str | None = None,
) -> pd.DataFrame:
    frame = df.copy()

    frame.columns = [str(col).strip() for col in frame.columns]
    rename_map = {}
    for col in frame.columns:
        alias = COLUMN_ALIASES.get(col)
        if alias:
            rename_map[col] = alias

    frame = frame.rename(columns=rename_map)

    dt_col = _find_datetime_column(frame)
    if not dt_col:
        raise ValueError(
            f"weather-rp5 returned data without datetime column. "
            f"Available columns: {', '.join(map(str, frame.columns))}"
        )

    dt = pd.to_datetime(frame[dt_col], errors="coerce")
    if dt.isna().all():
        raise ValueError(
            f"Не удалось распарсить колонку времени '{dt_col}'. "
            f"Available columns: {', '.join(map(str, frame.columns))}"
        )

    frame["local_date"] = dt.dt.strftime("%Y-%m-%d")
    frame["local_time"] = dt.dt.strftime("%H:%M")
    frame["datetime_local"] = dt.dt.strftime("%Y-%m-%d %H:%M")

    frame["city"] = city_name
    frame["station_name"] = extract_station_name(city_name, rp5_url, station_name)
    frame["wmo_id"] = wmo_id
    frame["source_url"] = rp5_url

    for col in RP5_CANONICAL_COLUMNS:
        if col not in frame.columns:
            frame[col] = None

    return frame[RP5_CANONICAL_COLUMNS]


def fetch_city_weather(city_name: str, date_from: str, date_to: str) -> pd.DataFrame:
    station = resolve_station(city_name)
    rp5_url = station["rp5_url"]
    station_name = station["station_name"]

    station_id = get_station_id(rp5_url)
    start = date.fromisoformat(date_from)
    end = date.fromisoformat(date_to)

    is_metar = "metar" in rp5_url.lower()
    df = get_weather_data(station_id, start, end, is_metar)

    if df is None or df.empty:
        raise ValueError(f"Не удалось получить данные по станции {station_name}")

    return _normalize_weather_rp5_frame(
        df=df,
        city_name=city_name,
        rp5_url=rp5_url,
        wmo_id=str(station_id),
        station_name=station_name,
    ).reset_index(drop=True)
