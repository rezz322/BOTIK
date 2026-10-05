# -*- coding: utf-8 -*-
import math
import html
import re

# Координати та ідентифікатори
SARNY_LAT = 51.3378
SARNY_LNG = 26.6344
SARNY_RADIUS_KM = 65.0

RIVNE_STATE_ID = "5"
SARNY_DISTRICT_ID = "113"

# 11 територіальних громад Сарненського району (підрайони)
SARNY_COMMUNITIES = {
    "sarny_tg": {
        "id": "sarny_tg",
        "name": "Сарненська міська громада",
        "short_name": "Сарни",
        "lat": 51.3378,
        "lng": 26.6344,
        "keywords": ["сарненськ", "сарни", "sarn"],
    },
    "dubrovytsia_tg": {
        "id": "dubrovytsia_tg",
        "name": "Дубровицька міська громада",
        "short_name": "Дубровиця",
        "lat": 51.5750,
        "lng": 26.5650,
        "keywords": ["дубровиц", "дубровицьк", "dubrovyts"],
    },
    "rokytne_tg": {
        "id": "rokytne_tg",
        "name": "Рокитнівська селищна громада",
        "short_name": "Рокитне",
        "lat": 51.2796,
        "lng": 27.2144,
        "keywords": ["рокитн", "рокитнівськ", "томашгород", "rokytn"],
    },
    "klesiv_tg": {
        "id": "klesiv_tg",
        "name": "Клесівська селищна громада",
        "short_name": "Клесів",
        "lat": 51.3167,
        "lng": 26.8972,
        "keywords": ["клесів", "клесов", "клесівськ", "klesiv"],
    },
    "stepan_tg": {
        "id": "stepan_tg",
        "name": "Степанська селищна громада",
        "short_name": "Степань",
        "lat": 51.1278,
        "lng": 26.3056,
        "keywords": ["степан", "степанськ", "stepan"],
    },
    "berezove_tg": {
        "id": "berezove_tg",
        "name": "Березівська сільська громада",
        "short_name": "Березове",
        "lat": 51.5833,
        "lng": 27.3500,
        "keywords": ["березівськ", "березов", "березове", "berezov"],
    },
    "vyry_tg": {
        "id": "vyry_tg",
        "name": "Вирівська сільська громада",
        "short_name": "Вири",
        "lat": 26.9333,
        "lng": 26.9333,
        "keywords": ["вирівськ", "вири", "чудель", "vyry"],
    },
    "vysotsk_tg": {
        "id": "vysotsk_tg",
        "name": "Висоцька сільська громада",
        "short_name": "Висоцьк",
        "lat": 51.7236,
        "lng": 26.6556,
        "keywords": ["висоцьк", "висоцьк", "vysotsk"],
    },
    "myliach_tg": {
        "id": "myliach_tg",
        "name": "Миляцька сільська громада",
        "short_name": "Миляч",
        "lat": 51.6800,
        "lng": 26.8200,
        "keywords": ["миляцьк", "миляч", "myliach"],
    },
    "nemovychi_tg": {
        "id": "nemovychi_tg",
        "name": "Немовицька сільська громада",
        "short_name": "Немовичі",
        "lat": 51.2000,
        "lng": 26.5667,
        "keywords": ["немович", "немовицьк", "nemovych"],
    },
    "stareselo_tg": {
        "id": "stareselo_tg",
        "name": "Старосільська сільська громада",
        "short_name": "Старе Село",
        "lat": 51.6917,
        "lng": 27.2000,
        "keywords": ["старосільськ", "старе село", "stareselo"],
    },
}

# Fix vyry_tg lat
SARNY_COMMUNITIES["vyry_tg"]["lat"] = 51.2333

# Загальні налаштування для Сарненського району
MONITORED_REGIONS = {
    "sarny": {
        "id": "sarny",
        "name": "Сарненський район",
        "short_name": "Сарни",
        "lat": SARNY_LAT,
        "lng": SARNY_LNG,
        "radius_km": SARNY_RADIUS_KM,
        "keywords": [
            "сарн", "дубровиц", "рокитн", "клесів", "степань", "немович",
            "вири", "висоцьк", "миляцьк", "березн", "костопіль", "північ рівнен"
        ],
        "oblast_keywords": ["rivnenska", "рівненськ", "рівне", "rivne"],
        "raion_keywords": ["sarnen", "сарненськ", "сарни"],
    },
}

THREAT_TRANSLATION = {
    "drone": "🛵 БпЛА (Шахед)",
    "ballistic": "🚀 Балістична загроза",
    "cruise": "🚀 Крилата ракета",
    "kab": "💣 КАБ (керована авіабомба)",
    "aviation": "✈️ Тактична авіація",
    "recon": "🛰 Розвідувальний БпЛА",
    "fpv": "🛸 FPV-дрон",
    "unknown": "⚠️ Повітряна загроза",
}


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Обчислює відстань по поверхні Землі у кілометрах між двома координатами."""
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = (
        math.sin(dlat / 2) ** 2
        + math.cos(math.radians(lat1))
        * math.cos(math.radians(lat2))
        * math.sin(dlon / 2) ** 2
    )
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def heading_to_compass(deg) -> str:
    """Перетворює курс польоту у зрозумілий людині напрямок."""
    if deg is None:
        return ""
    try:
        val = int((float(deg) / 45.0) + 0.5) % 8
        compass = [
            "Північ ⬆️",
            "Північний схід ↗️",
            "Схід ➡️",
            "Південний схід ↘️",
            "Південь ⬇️",
            "Південний захід ↙️",
            "Захід ⬅️",
            "Північний захід ↖️",
        ]
        return f"{round(float(deg))}° ({compass[val]})"
    except Exception:
        return f"{deg}°"


def clean_text_line(s: str) -> str:
    """Видаляє зайві символи, посилання та пробіли."""
    s = re.sub(r"\(@[a-zA-Z0-9_]+\)", "", s)
    s = re.sub(r"@[a-zA-Z0-9_]+", "", s)
    s = re.sub(r"https?://\S+", "", s)
    return re.sub(r"[ \t]+", " ", s).strip()


def format_telegram_html(text: str) -> str:
    """Безпечно форматує текст для Telegram HTML."""
    escaped = html.escape(text or "")
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
    return escaped


def format_duration(total_seconds: float) -> str:
    """Форматує тривалість тривоги у безпечний для Telegram HTML вигляд."""
    total_minutes = int(total_seconds // 60)
    if total_minutes < 1:
        return "менше 1 хв."
    hours = total_minutes // 60
    mins = total_minutes % 60
    if hours > 0:
        return f"{hours} год. {mins} хв."
    return f"{mins} хв."
