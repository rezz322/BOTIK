# -*- coding: utf-8 -*-
import math
import html
import re

# Налаштування регіонів для моніторингу
MONITORED_REGIONS = {
    "sarny": {
        "id": "sarny",
        "name": "Сарненський район",
        "short_name": "Сарни",
        "lat": 51.3378,
        "lng": 26.6344,
        "radius_km": 60.0,
        "keywords": [
            "сарн", "дубровиц", "рокитн", "клесів", "степань", "немович",
            "вири", "висоцьк", "миляцьк", "березн", "костопіль", "північ рівнен"
        ],
        "oblast_keywords": ["rivnenska", "рівненськ", "рівне", "rivne"],
        "raion_keywords": ["sarnen", "сарненськ", "сарни"],
        "kupol_raion_id": "сарненський",
        "kupol_strict_keywords": [],
        "kupol_strict_radius_km": 60.0,
        "feed_strict_keywords": [],
        "env_thread_key": "THREAD_ID_ALERTS",
    },
}

# Координати та ключові слова Сарн
SARNY_LAT = MONITORED_REGIONS["sarny"]["lat"]
SARNY_LNG = MONITORED_REGIONS["sarny"]["lng"]
SARNY_RADIUS_KM = MONITORED_REGIONS["sarny"]["radius_km"]
SARNY_KEYWORDS = MONITORED_REGIONS["sarny"]["keywords"]

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
    """Перетворює азимут/градуси курсу польоту у зрозумілий людині напрямок зі стрілочкою."""
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


def extract_kupol_location(note: str, region_name: str) -> str:
    """
    Визначає найбільш інформативну назву локації для загрози КУПОЛ.
    Якщо regionNameUk порожній, витягує назву населеного пункту/області з noteUk.
    """
    if region_name and region_name.strip():
        return region_name.strip()
    if not note:
        return "Україна"
    clean_n = clean_text_line(note)
    if "—" in clean_n:
        part = clean_n.split("—", 1)[1].split(".")[0].strip()
        if part:
            return part
    if "курсом на" in clean_n.lower():
        idx = clean_n.lower().find("курсом на")
        part = clean_n[idx:].split(".")[0].strip()
        if part:
            return part
    first_sentence = clean_n.split(".")[0].strip()
    return first_sentence if first_sentence else "Україна"


def line_matches_region(line: str, region_cfg: dict) -> bool:
    """Перевіряє, чи містить рядок ключові слова зазначеного регіону."""
    l = line.lower()
    return any(k in l for k in region_cfg.get("keywords", []))


def line_matches_sarny(line: str) -> bool:
    return line_matches_region(line, MONITORED_REGIONS["sarny"])


def is_bullet_line(s: str) -> bool:
    """Визначає, чи є рядок пунктом списку (стрілочка, маркер, дефіс, номер тощо)."""
    st = s.strip()
    if st.startswith(("→", "->", "•", "◦", "–", "—", ">")):
        return True
    if st.startswith(("- ", "* ", "+ ")):
        return True
    if re.match(r"^\d+[\.\)]\s*", st):
        return True
    return False


def is_header_line(s: str) -> bool:
    """Визначає, чи є рядок заголовком області/напрямку."""
    st = s.strip()
    if not st or is_bullet_line(st):
        return False
    if st.endswith(":") or st.endswith(":-"):
        return True
    if st.startswith("**") and st.endswith("**") and len(st) > 4:
        return True
    if st.startswith("#"):
        return True
    if re.match(r"^[\U00010000-\U0010ffff\u2600-\u27bf\u2b50].*:", st):
        return True
    return False


def clean_text_line(s: str) -> str:
    """Видаляє юзернейми каналів (@channel), посилання та зайві пробіли."""
    s = re.sub(r"\(@[a-zA-Z0-9_]+\)", "", s)
    s = re.sub(r"@[a-zA-Z0-9_]+", "", s)
    s = re.sub(r"https?://\S+", "", s)
    return re.sub(r"[ \t]+", " ", s).strip()


def filter_relevant_lines_for_region(text: str, region_cfg: dict) -> str:
    """
    Фільтрує текст моніторингу по рядках для обраного регіону (Сарни тощо).
    """
    if not text:
        return ""

    paragraphs = re.split(r"\n\s*\n", text.strip())
    kept_chunks = []

    for para in paragraphs:
        lines = [l.strip() for l in para.splitlines() if l.strip()]
        if not lines:
            continue

        sub_sections = []
        cur_header = None
        cur_items = []

        for idx, line in enumerate(lines):
            looks_header = is_header_line(line)
            if idx == 0 and len(lines) > 1 and not is_bullet_line(line) and (
                line.endswith(":") or any(w in line.lower() for w in ["область", "щина", "напрямок", "сектор", "район"])
            ):
                looks_header = True

            if looks_header:
                if cur_header or cur_items:
                    sub_sections.append((cur_header, cur_items))
                cur_header = line
                cur_items = []
            else:
                cur_items.append(line)

        if cur_header or cur_items:
            sub_sections.append((cur_header, cur_items))

        for header, items in sub_sections:
            matched_items = [clean_text_line(it) for it in items if line_matches_region(it, region_cfg)]
            matched_items = [it for it in matched_items if it]
            if matched_items:
                res = []
                if header:
                    clean_h = clean_text_line(header)
                    if clean_h:
                        res.append(clean_h)
                res.extend(matched_items)
                kept_chunks.append("\n".join(res))
            elif header and line_matches_region(header, region_cfg):
                res = []
                clean_h = clean_text_line(header)
                if clean_h:
                    res.append(clean_h)
                for it in items:
                    cit = clean_text_line(it)
                    if cit:
                        res.append(cit)
                kept_chunks.append("\n".join(res))
            elif not header:
                matched = [clean_text_line(it) for it in items if line_matches_region(it, region_cfg)]
                matched = [it for it in matched if it]
                if matched:
                    kept_chunks.append("\n".join(matched))

    if kept_chunks:
        return "\n\n".join(kept_chunks)

    fallback_lines = [clean_text_line(l) for l in text.splitlines() if l.strip() and line_matches_region(l, region_cfg)]
    fallback_lines = [l for l in fallback_lines if l]
    if fallback_lines:
        return "\n".join(fallback_lines)

    return ""


def filter_relevant_lines(text: str) -> str:
    """Сумісність зі старим кодом (за замовчуванням Сарни)."""
    return filter_relevant_lines_for_region(text, MONITORED_REGIONS["sarny"])


def format_telegram_html(text: str) -> str:
    """Безпечно форматує текст для Telegram HTML режиму."""
    escaped = html.escape(text or "")
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
    return escaped


def format_duration(total_seconds: float) -> str:
    """Форматує тривалість тривоги у безпечний для Telegram HTML вигляд (без небезпечних символів <)."""
    total_minutes = int(total_seconds // 60)
    if total_minutes < 1:
        return "менше 1 хв."
    hours = total_minutes // 60
    mins = total_minutes % 60
    if hours > 0:
        return f"{hours} год. {mins} хв."
    return f"{mins} хв."
