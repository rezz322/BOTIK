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


def filter_relevant_lines(text: str) -> str:
    """
    Фільтрує текст моніторингу по рядках:
    Залишає тільки рядки та відповідні блоки (заголовки областей),
    що стосуються Сарненського району / напрямку, відсікаючи інші області та міста.
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
            matched_items = [it for it in items if line_matches_sarny(it)]
            if matched_items:
                res = []
                if header:
                    res.append(header)
                res.extend(matched_items)
                kept_chunks.append("\n".join(res))
            elif header and line_matches_sarny(header):
                res = [header]
                res.extend(items)
                kept_chunks.append("\n".join(res))
            elif not header:
                matched = [it for it in items if line_matches_sarny(it)]
                if matched:
                    kept_chunks.append("\n".join(matched))

    if kept_chunks:
        return "\n\n".join(kept_chunks)

    # Запасний варіант: якщо блочна структура не знайшла збігів, перевіряємо по рядках
    fallback_lines = [l.strip() for l in text.splitlines() if l.strip() and line_matches_sarny(l)]
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

    def get_status(self) -> dict:
        """
        Отримує повну актуальну інформацію з eRadar для Сарненського району:
        1. Статус тривоги (Тривога / Відбій)
        2. Активні цілі (Dangers), що загрожують району
        3. Повідомлення моніторингу (Feed) з курсом руху
        """
        result = {
            "is_alarm": False,
            "alarm_text": "🟢 ВІДБІЙ",
            "dangers": [],
            "feed_events": [],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

        # 1. Перевірка статусу повітряної тривоги
        try:
            r = self.session.get("https://eradar.app/api/alerts", impersonate="chrome124", timeout=15)
            if r.status_code == 200:
                alerts_data = r.json()
                active = alerts_data.get("active", [])
                is_rivne = any("рівнен" in x.lower() or "сарн" in x.lower() for x in active)
                result["is_alarm"] = is_rivne
                result["alarm_text"] = "🔴 ПОВІТРЯНА ТРИВОГА" if is_rivne else "🟢 ВІДБІЙ"
        except Exception as e:
            logger.error(f"Помилка отримання alerts: {e}")

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

        # 2. Нові цілі, що летять в район (Dangers)
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
                    f"🚨 <b>ЗАГРОЗА ДЛЯ САРНЕНСЬКОГО РАЙОНУ!</b>\n\n"
                    f"🎯 <b>Загроза:</b> {d['threat_type']}\n"
                    f"📍 <b>Вектор:</b> {vector_info}"
                    f"{fly_info_block}\n"
                    f"⏰ <b>Час:</b> {now_str}"
                )
                logger.warning(f"Нова ціль для Сарн: {d['threat_type']} -> {d['place']}")
                if self.send_to_telegram:
                    self.sender._send_text_message(msg, thread_id=self.thread_id)

        # 3. Нові моніторингові повідомлення (тільки якщо не було надіслано в Dangers)
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
                f"📡 <b>Сарненський район:</b>\n\n"
                f"💬 <i>{text_html}</i>\n\n"
                f"⏰ <b>Час:</b> {now_str}"
            )
            logger.info(f"Нове повідомлення моніторингу: {text_to_show}")
            if self.send_to_telegram:
                self.sender._send_text_message(msg, thread_id=self.thread_id)

    def run_live(self, poll_interval: int = 15):
        """Запускає постійний моніторинг у реальному часі."""
        logger.info("🛰 Запуск живого моніторингу eRadar для Сарненського району...")
        logger.info(f"📌 Цільова ветка (thread_id): {self.thread_id}")
        logger.info(f"⏱ Інтервал перевірки: кожні {poll_interval} сек.")

        init_data = self.get_status()
        self.is_alarm_active = init_data["is_alarm"]
        logger.info(f"📌 Поточний статус тривоги: {init_data['alarm_text']}")
        logger.info(f"🎯 Активних загроз для Сарн зараз: {len(init_data['dangers'])}")

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
    print("📍 ДАНІ З ERADAR.APP ДЛЯ САРНЕНСЬКОГО РАЙОНУ:")
    print(f"Статус тривоги: {data['alarm_text']}")
    print(f"Цільовий Thread ID: {monitor.thread_id}")
    print(f"Активних цілей у напрямку району: {len(data['dangers'])}")
    print("=" * 60)
    # Запуск постійного моніторингу в реальному часі (кожні 15 сек)
    monitor.run_live(poll_interval=15)

