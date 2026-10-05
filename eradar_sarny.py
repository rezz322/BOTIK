import math
import time
import sys
import logging
import html
import re
from datetime import datetime, timezone
from curl_cffi import requests

# Налаштування виводу консолі
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, THREAD_ID_ALERTS
from telegram_sender import TelegramSender

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("eRadarSarny")

# Координати центру Сарн
SARNY_LAT = 51.3378
SARNY_LNG = 26.6344
SARNY_RADIUS_KM = 55.0  # Радіус охоплення району

# Ключові слова для фільтрації по Сарненському району та прилеглих точках
SARNY_KEYWORDS = [
    "сарн",          # Сарни, Сарненський, Сарненщина, Сарнах
    "дубровиц",      # Дубровиця, Дубровицький
    "рокитн",        # Рокитне, Рокитнівський
    "клесів",        # Клесів
    "степань",       # Степань
    "немович",       # Немовичі
    "вири",          # Вири
    "висоцьк",       # Висоцьк
    "миляцьк",       # Миляцьк
    "березн",        # Березне
    "костопіль",     # Костопіль
    "північ рівнен", # північ Рівненщини / північ Рівненської
]

THREAT_TRANSLATION = {
    "drone": "🛵 БпЛА (Шахед)",
    "ballistic": "🚀 Балістична загроза",
    "cruise": "🚀 Крилата ракета",
    "kab": "💣 КАБ (керована авіабомба)",
    "aviation": "✈️ Тактична авіація",
    "recon": "🛰 Розвідувальний БпЛА",
    "unknown": "⚠️ Повітряна загроза",
}


def haversine_km(lat1, lon1, lat2, lon2):
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
    """Перетворює азимут/градуси курсу польоту у зрозумілий людині напрямок."""
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


def line_matches_sarny(line: str) -> bool:
    """Перевіряє, чи містить рядок ключові слова Сарненського району."""
    l = line.lower()
    return any(k in l for k in SARNY_KEYWORDS)


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
    # Емодзі + текст із двокрапкою (наприклад, ✈️Чернігівщина:)
    if re.match(r"^[\U00010000-\U0010ffff\u2600-\u27bf\u2b50].*:", st):
        return True
    return False


def clean_text_line(s: str) -> str:
    """Видаляє юзернейми каналів (@channel), посилання та зайві пробіли."""
    s = re.sub(r"\(@[a-zA-Z0-9_]+\)", "", s)
    s = re.sub(r"@[a-zA-Z0-9_]+", "", s)
    s = re.sub(r"https?://\S+", "", s)
    return re.sub(r"[ \t]+", " ", s).strip()


def filter_relevant_lines(text: str) -> str:
    """
    Фільтрує текст моніторингу по рядках:
    Залишає тільки рядки та відповідні блоки (заголовки областей),
    що стосуються Сарненського району / напрямку, відсікаючи інші області, міста,
    а також видаляє згадки каналів та посилання.
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
            # Якщо перший рядок блоку схожий на назву регіону без двокрапки
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
            matched_items = [clean_text_line(it) for it in items if line_matches_sarny(it)]
            matched_items = [it for it in matched_items if it]
            if matched_items:
                res = []
                if header:
                    clean_h = clean_text_line(header)
                    if clean_h:
                        res.append(clean_h)
                res.extend(matched_items)
                kept_chunks.append("\n".join(res))
            elif header and line_matches_sarny(header):
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
                matched = [clean_text_line(it) for it in items if line_matches_sarny(it)]
                matched = [it for it in matched if it]
                if matched:
                    kept_chunks.append("\n".join(matched))

    if kept_chunks:
        return "\n\n".join(kept_chunks)

    # Запасний варіант: якщо блочна структура не знайшла збігів, перевіряємо по рядках
    fallback_lines = [clean_text_line(l) for l in text.splitlines() if l.strip() and line_matches_sarny(l)]
    fallback_lines = [l for l in fallback_lines if l]
    if fallback_lines:
        return "\n".join(fallback_lines)

    return ""


def format_telegram_html(text: str) -> str:
    """Безпечно форматує текст для Telegram HTML режиму."""
    escaped = html.escape(text or "")
    escaped = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", escaped)
    return escaped


def format_duration(total_seconds: float) -> str:
    """Форматує тривалість тривоги у людиночитабельний вигляд."""
    total_minutes = int(total_seconds // 60)
    if total_minutes < 1:
        return "< 1 хв."
    hours = total_minutes // 60
    mins = total_minutes % 60
    if hours > 0:
        return f"{hours} год. {mins} хв."
    return f"{mins} хв."


class SarnyRadarMonitor:
    def __init__(self, send_to_telegram: bool = True):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json",
        })
        self.send_to_telegram = send_to_telegram
        self.sender = TelegramSender(token=TELEGRAM_BOT_TOKEN, channel=TELEGRAM_CHAT_ID)
        self.thread_id = THREAD_ID_ALERTS

        self.is_alarm_active = False
        self.alarm_start_time = None
        self.seen_danger_ids = set()
        self.seen_feed_ids = set()
        self.seen_message_keys = set()
        self.seen_text_hashes = set()
        self.seen_kupol_ids = set()

    def check_sarny_alarm(self) -> bool:
        """
        Перевіряє статус повітряної тривоги ВИКЛЮЧНО для Сарненського району:
        1. Запитує районний статус з alerts.in.ua (деталізація по конкретних районах).
        2. Якщо тривога лише в Рівненському, Дубенському чи Вараському районі — для Сарн тривога НЕ вмикається.
        3. Запасний варіант 1: перевірка офіційних повідомлень @UkraineAlarmSignal у стрічці eRadar.
        4. Запасний варіант 2: перевірка районних тривог з сервісу КУПОЛ (kupol.in.ua).
        """
        # 1. Основне джерело: alerts.in.ua з районною деталізацією
        try:
            r = self.session.get("https://api.alerts.in.ua/v3/alerts/active.md", impersonate="chrome124", timeout=10)
            if r.status_code == 200:
                txt = r.text
                sec3_idx = txt.find("## 3. CURRENT WARNING STATUS")
                sec4_idx = txt.find("## 4.", sec3_idx) if sec3_idx != -1 else -1
                sec3 = txt[sec3_idx:sec4_idx] if sec3_idx != -1 and sec4_idx != -1 else txt[sec3_idx:]

                # Шукаємо запис по Рівненській області
                for para in sec3.split("\n\n"):
                    para_s = para.strip()
                    if "rivnenska oblast" in para_s.lower() or "рівненська область" in para_s.lower():
                        # Тривога десь у Рівненській області
                        # Перевіряємо, чи саме в Сарненському районі
                        if "sarnen" in para_s.lower() or "сарненськ" in para_s.lower():
                            return True
                        elif "all areas" in para_s.lower() or "всі райони" in para_s.lower():
                            return True
                        else:
                            # Тривога в іншому районі (наприклад, Рівненському чи Дубенському)
                            return False

                # Рівненської області взагалі немає в активних тривогах
                return False
        except Exception as e:
            logger.error(f"Помилка отримання районного статусу з alerts.in.ua: {e}")

        # 2. Запасне джерело 1: перевірка останніх повідомлень @UkraineAlarmSignal у стрічці eRadar
        try:
            r = self.session.get("https://eradar.app/api/feed?limit=50", impersonate="chrome124", timeout=10)
            if r.status_code == 200:
                feed = r.json().get("feed", [])
                for item in feed:
                    if item.get("channel") == "UkraineAlarmSignal":
                        txt = (item.get("text") or "").lower()
                        if "сарненськ" in txt:
                            if "🟢" in txt or "відбій" in txt:
                                return False
                            if "🔴" in txt or "🟡" in txt or "тривог" in txt:
                                return True
        except Exception as e:
            logger.error(f"Помилка отримання стрічки UkraineAlarmSignal: {e}")

        # 3. Запасне джерело 2: перевірка районних тривог сервісу КУПОЛ (kupol.in.ua)
        try:
            r = self.session.get("https://kupol.in.ua/api/alerts/active", timeout=10)
            if r.status_code == 200:
                alerts = r.json().get("alerts", [])
                for a in alerts:
                    reg_id = str(a.get("regionId") or "").lower()
                    reg_name = str(a.get("regionNameUk") or "").lower()
                    if "сарненськ" in reg_id or "сарненськ" in reg_name:
                        return a.get("status") == "active"
        except Exception as e:
            logger.error(f"Помилка отримання районного статусу з КУПОЛ: {e}")

        return False

    def get_kupol_threats(self) -> list:
        """
        Отримує активні загрози від додаткового сервісу КУПОЛ (kupol.in.ua / NEPTUN):
        1. Запитує https://kupol.in.ua/api/threats/active
        2. Фільтрує загрози по координатах до Сарн (радіус SARNY_RADIUS_KM) або по ключових словах Сарненщини в описі чи назві регіону.
        3. Розраховує азимут/напрямок руху та дистанцію.
        """
        threats_found = []
        try:
            r = self.session.get("https://kupol.in.ua/api/threats/active", timeout=10)
            if r.status_code == 200:
                threats = r.json().get("threats", [])
                for t in threats:
                    tid = str(t.get("id"))
                    coords = t.get("coordinates")
                    lat, lng = None, None
                    dist = 9999
                    if coords and len(coords) >= 2:
                        # Формат координат у КУПОЛ: [lng, lat]
                        lng = coords[0]
                        lat = coords[1]
                        dist = haversine_km(SARNY_LAT, SARNY_LNG, lat, lng)

                    note = t.get("noteUk") or ""
                    region = t.get("regionNameUk") or ""
                    comb_text = f"{note} {region}".lower()

                    is_sarny_area = (dist <= SARNY_RADIUS_KM) or any(k in comb_text for k in SARNY_KEYWORDS)

                    if is_sarny_area:
                        heading = t.get("headingDeg")
                        course_desc = heading_to_compass(heading) if heading is not None else None

                        raw_kind = (t.get("kind") or "").lower()
                        raw_label = t.get("labelUk") or raw_kind

                        if "fpv" in raw_kind or "fpv" in raw_label.lower():
                            threat_icon = "🛸"
                        elif "uav" in raw_kind or "дрон" in raw_label.lower() or "бпла" in raw_label.lower():
                            threat_icon = "🛵"
                        elif "missile" in raw_kind or "ракет" in raw_label.lower() or "баліст" in raw_label.lower():
                            threat_icon = "🚀"
                        elif "kab" in raw_kind or "каб" in raw_label.lower():
                            threat_icon = "💣"
                        elif "aviation" in raw_kind or "авіа" in raw_label.lower():
                            threat_icon = "✈️"
                        else:
                            threat_icon = "🎯"

                        threat_display = f"{threat_icon} {raw_label}"

                        threats_found.append({
                            "id": tid,
                            "threat_type": threat_display,
                            "note": note,
                            "region": region,
                            "heading": heading,
                            "course_desc": course_desc,
                            "distance_km": round(dist, 1) if dist < 9999 else None,
                            "lat": lat,
                            "lng": lng,
                            "source_label": t.get("sourceLabel") or "NEPTUN",
                        })
        except Exception as e:
            logger.error(f"Помилка отримання даних з КУПОЛ (kupol.in.ua): {e}")

        return threats_found

    def get_status(self) -> dict:
        """
        Отримує повну актуальну інформацію з eRadar та додаткового сервісу КУПОЛ для Сарненського району:
        1. Статус тривоги (Тривога / Відбій)
        2. Активні цілі (Dangers) з eRadar
        3. Повідомлення моніторингу (Feed) з курсом руху
        4. Активні цілі з координатами та азимутом з сервісу КУПОЛ (NEPTUN)
        """
        result = {
            "is_alarm": False,
            "alarm_text": "🟢 ВІДБІЙ",
            "dangers": [],
            "feed_events": [],
            "kupol_threats": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # 1. Перевірка статусу повітряної тривоги ВИКЛЮЧНО для Сарненського району
        is_sarny = self.check_sarny_alarm()
        result["is_alarm"] = is_sarny
        result["alarm_text"] = "🔴 ПОВІТРЯНА ТРИВОГА" if is_sarny else "🟢 ВІДБІЙ"

        # 2. Перевірка активних цілей (куда летит, тип загрози)
        danger_feed_ids = set()
        danger_message_keys = set()
        try:
            r = self.session.get("https://eradar.app/api/dangers", impersonate="chrome124", timeout=15)
            if r.status_code == 200:
                dangers = r.json().get("dangers", [])
                for d in dangers:
                    name = (d.get("canonical_name") or "").lower()
                    lat = d.get("lat")
                    lng = d.get("lng")
                    dist = haversine_km(SARNY_LAT, SARNY_LNG, lat, lng) if (lat and lng) else 9999

                    is_sarny_area = any(k in name for k in SARNY_KEYWORDS) or (dist <= SARNY_RADIUS_KM)
                    if is_sarny_area:
                        threat_raw = d.get("threat_type", "unknown")
                        threat_title = THREAT_TRANSLATION.get(threat_raw, threat_raw)
                        raw_excerpt = d.get("message_excerpt") or ""
                        filtered_excerpt = filter_relevant_lines(raw_excerpt)

                        last_msg_id = d.get("last_message_id")
                        tg_msg_id = d.get("tg_message_id")
                        ch = d.get("channel")

                        if last_msg_id:
                            danger_feed_ids.add(str(last_msg_id))
                        if ch and tg_msg_id:
                            danger_message_keys.add(f"{ch}_{tg_msg_id}")

                        result["dangers"].append({
                            "id": d.get("id"),
                            "threat_type": threat_title,
                            "place": d.get("canonical_name"),
                            "distance_km": round(dist, 1) if dist < 9999 else None,
                            "channel": ch,
                            "text": filtered_excerpt or raw_excerpt,
                            "raw_text": raw_excerpt,
                            "expires_at": d.get("expires_at"),
                            "last_message_id": last_msg_id,
                            "tg_message_id": tg_msg_id,
                        })
        except Exception as e:
            logger.error(f"Помилка отримання dangers: {e}")

        # 3. Перевірка стрічки моніторингу (напрямки, сектори)
        try:
            r = self.session.get("https://eradar.app/api/feed?limit=50", impersonate="chrome124", timeout=15)
            if r.status_code == 200:
                feed = r.json().get("feed", [])
                for item in feed:
                    fid = str(item.get("id"))
                    ch = item.get("channel")
                    tg_id = item.get("tg_message_id")
                    msg_key = f"{ch}_{tg_id}" if ch and tg_id else None

                    # Якщо це повідомлення вже виявлено як активна ціль (Danger), не дублюємо його у Feed!
                    if fid in danger_feed_ids or (msg_key and msg_key in danger_message_keys):
                        continue

                    raw_text = item.get("text") or ""
                    filtered_text = filter_relevant_lines(raw_text)
                    if not filtered_text:
                        continue

                    item["filtered_text"] = filtered_text
                    result["feed_events"].append(item)
        except Exception as e:
            logger.error(f"Помилка отримання feed: {e}")

        # 4. Перевірка активних цілей від додаткового сервісу КУПОЛ (kupol.in.ua / NEPTUN)
        result["kupol_threats"] = self.get_kupol_threats()

        return result

    def check_and_notify(self):
        """Перевіряє зміни та надсилає сповіщення при появі загроз чи зміні тривоги у гілку 'Тривога'."""
        data = self.get_status()
        current_alarm = data["is_alarm"]

        # 1. Зміна статусу тривоги (Початок / Відбій)
        now_str = datetime.now().strftime("%H:%M:%S")
        if current_alarm != self.is_alarm_active:
            if current_alarm:
                self.alarm_start_time = datetime.now()
                msg = (
                    f"🔴 <b>УВАГА! ПОВІТРЯНА ТРИВОГА!</b>\n\n"
                    f"📍 <b>Сарненський район</b>\n"
                    f"⏰ <b>Час початку:</b> {now_str}\n\n"
                    f"⚠️ Перейдіть в укриття!"
                )
                logger.warning("Оголошено тривогу в районі!")
            else:
                duration_str = ""
                if self.alarm_start_time:
                    dur_sec = (datetime.now() - self.alarm_start_time).total_seconds()
                    duration_str = f"\n⏱ <b>Тривалість:</b> {format_duration(dur_sec)}"
                msg = (
                    f"🟢 <b>ВІДБІЙ ПОВІТРЯНОЇ ТРИВОГИ!</b>\n\n"
                    f"📍 <b>Сарненський район</b>\n"
                    f"⏰ <b>Час відбою:</b> {now_str}"
                    f"{duration_str}\n\n"
                    f"✅ Небезпека минула."
                )
                logger.info("Відбій тривоги в районі!")

            self.is_alarm_active = current_alarm
            if self.send_to_telegram:
                self.sender._send_text_message(msg, thread_id=self.thread_id)

        # 2. Нові цілі від основного сервісу eRadar (Dangers)
        for d in data["dangers"]:
            did = str(d["id"])
            last_msg_id = str(d["last_message_id"]) if d.get("last_message_id") else None
            msg_key = f"{d.get('channel')}_{d.get('tg_message_id')}" if d.get("channel") and d.get("tg_message_id") else None

            # Запобігаємо дублюванню цього ж повідомлення через feed
            if last_msg_id:
                self.seen_feed_ids.add(last_msg_id)
            if msg_key:
                self.seen_message_keys.add(msg_key)

            if did not in self.seen_danger_ids:
                self.seen_danger_ids.add(did)

                dist_str = f" (~{d['distance_km']} км)" if d.get('distance_km') else ""
                place_text = format_telegram_html(d.get("place") or "")
                vector_info = f"{place_text}{dist_str}" if place_text else "Сарненський район"

                # Куди летить / деталі напрямку для Сарненського району
                det_text = (d.get('text') or '').strip()
                fly_info_block = ""
                if det_text and det_text != '—':
                    det_html = format_telegram_html(det_text)
                    fly_info_block = f"\n🧭 <b>Куди летить:</b>\n{det_html}"

                msg = (
                    f"🚨 <b>[eRadar] ЗАГРОЗА ДЛЯ САРНЕНСЬКОГО РАЙОНУ!</b>\n\n"
                    f"🎯 <b>Загроза:</b> {d['threat_type']}\n"
                    f"📍 <b>Вектор:</b> {vector_info}"
                    f"{fly_info_block}\n"
                    f"⏰ <b>Час:</b> {now_str}\n\n"
                    f"📡 <i>Джерело: eRadar.app</i>"
                )
                logger.warning(f"[eRadar] Нова ціль для Сарн: {d['threat_type']} -> {d['place']}")
                if self.send_to_telegram:
                    self.sender._send_text_message(msg, thread_id=self.thread_id)

        # 3. Нові моніторингові повідомлення eRadar (тільки якщо не було надіслано в Dangers)
        for f in data["feed_events"]:
            fid = str(f.get("id"))
            msg_key = f"{f.get('channel')}_{f.get('tg_message_id')}" if f.get("channel") and f.get("tg_message_id") else None

            # Пропускаємо дублікати
            if fid in self.seen_feed_ids or (msg_key and msg_key in self.seen_message_keys):
                continue

            self.seen_feed_ids.add(fid)
            if msg_key:
                self.seen_message_keys.add(msg_key)

            text_to_show = f.get("filtered_text") or filter_relevant_lines(f.get("text", ""))
            if not text_to_show:
                continue

            text_html = format_telegram_html(text_to_show)

            msg = (
                f"📡 <b>[eRadar Моніторинг] Сарненський район:</b>\n\n"
                f"💬 <i>{text_html}</i>\n\n"
                f"⏰ <b>Час:</b> {now_str}\n\n"
                f"📡 <i>Джерело: eRadar Feed</i>"
            )
            logger.info(f"[eRadar Feed] Нове повідомлення: {text_to_show}")
            if self.send_to_telegram:
                self.sender._send_text_message(msg, thread_id=self.thread_id)

        # 4. Нові цілі від додаткового сервісу КУПОЛ (kupol.in.ua / NEPTUN)
        for th in data.get("kupol_threats", []):
            kid = str(th["id"])
            if kid not in self.seen_kupol_ids:
                self.seen_kupol_ids.add(kid)

                dist_str = f" (~{th['distance_km']} км від Сарн)" if th.get("distance_km") else ""
                region_str = f"{th['region']}" if th.get("region") else "Сарненський район"
                loc_info = f"{region_str}{dist_str}"

                course_block = ""
                if th.get("course_desc"):
                    course_block = f"\n🧭 <b>Курс:</b> {th['course_desc']}"

                note_block = ""
                if th.get("note"):
                    clean_note = clean_text_line(th["note"])
                    note_html = format_telegram_html(clean_note)
                    note_block = f"\n💬 <b>Інформація:</b> {note_html}"

                msg = (
                    f"🛡 <b>[КУПОЛ / NEPTUN] ЗАГРОЗА ДЛЯ РАЙОНУ!</b>\n\n"
                    f"🎯 <b>Загроза:</b> {th['threat_type']}\n"
                    f"📍 <b>Локація:</b> {loc_info}"
                    f"{course_block}"
                    f"{note_block}\n"
                    f"⏰ <b>Час:</b> {now_str}\n\n"
                    f"📡 <i>Джерело: КУПОЛ (kupol.in.ua)</i>"
                )
                logger.warning(f"[КУПОЛ] Нова ціль для Сарн: {th['threat_type']} -> {th.get('note')}")
                if self.send_to_telegram:
                    self.sender._send_text_message(msg, thread_id=self.thread_id)

    def run_live(self, poll_interval: int = 15):
        """Запускає постійний моніторинг у реальному часі."""
        logger.info("🛰 Запуск живого моніторингу eRadar + КУПОЛ для Сарненського району...")
        logger.info(f"📌 Цільова ветка (thread_id): {self.thread_id}")
        logger.info(f"⏱ Інтервал перевірки: кожні {poll_interval} сек.")

        init_data = self.get_status()
        self.is_alarm_active = init_data["is_alarm"]
        logger.info(f"📌 Поточний статус тривоги: {init_data['alarm_text']}")
        logger.info(f"🎯 Активних цілей eRadar для Сарн: {len(init_data['dangers'])}")
        logger.info(f"🛡 Активних цілей КУПОЛ для Сарн: {len(init_data['kupol_threats'])}")

        while True:
            try:
                self.check_and_notify()
            except Exception as e:
                logger.error(f"Помилка циклу моніторингу: {e}")
            time.sleep(poll_interval)


if __name__ == "__main__":
    monitor = SarnyRadarMonitor(send_to_telegram=True)
    data = monitor.get_status()
    print("=" * 60)
    print("📍 ДАНІ З ERADAR + КУПОЛ ДЛЯ САРНЕНСЬКОГО РАЙОНУ:")
    print(f"Статус тривоги: {data['alarm_text']}")
    print(f"Цільовий Thread ID: {monitor.thread_id}")
    print(f"Активних цілей у напрямку району (eRadar): {len(data['dangers'])}")
    print(f"Активних цілей у напрямку району (КУПОЛ): {len(data['kupol_threats'])}")
    print("=" * 60)
    # Запуск постійного моніторингу в реальному часі (кожні 15 сек)
    monitor.run_live(poll_interval=15)


