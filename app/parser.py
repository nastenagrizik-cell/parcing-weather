from __future__ import annotations
from datetime import datetime
import pandas as pd


def fetch_city_weather(city_name: str, rp5_url: str, date_from: str, date_to: str) -> pd.DataFrame:
    return pd.DataFrame([
        {
            'city': city_name,
            'source_url': rp5_url,
            'date_from': date_from,
            'date_to': date_to,
            'loaded_at': datetime.utcnow().isoformat(timespec='seconds'),
            'note': 'MVP-заглушка. На следующем этапе сюда подключается реальная выгрузка архива RP5.'
        }
    ])
