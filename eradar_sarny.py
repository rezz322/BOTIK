import math
import time
import sys
import logging
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

# Ключові слова для фільтрації по Сарненському району
SARNY_KEYWORDS = [
    "сарненськ", "сарни", "Одеська", "Київська"
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
                        result["dangers"].append({
                            "id": d.get("id"),
                            "threat_type": threat_title,
                            "place": d.get("canonical_name"),
                            "distance_km": round(dist, 1) if dist < 9999 else None,
                            "channel": d.get("channel"),
                            "text": d.get("message_excerpt"),
                            "expires_at": d.get("expires_at"),
                        })
        except Exception as e:
            logger.error(f"Помилка отримання dangers: {e}")

        # 3. Перевірка стрічки моніторингу (напрямки, сектори)
        try:
            r = self.session.get("https://eradar.app/api/feed?limit=50", impersonate="chrome124", timeout=15)
            if r.status_code == 200:
                feed = r.json().get("feed", [])
                for item in feed:
                    txt = (item.get("text") or "").lower()
                    mentions = item.get("mentions", [])
                    matched = any(k in txt for k in SARNY_KEYWORDS) or any(
                        any(k in (m.get("place_query") or "").lower() for k in SARNY_KEYWORDS)
                        for m in mentions
                    )
                    if matched:
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
                    f"🔴 <b>УВАГА! ПОВІТРЯНА ТРИВОГА!</b>\n"
                    f"📍 <b>Сарненський район / Рівненщина</b>\n"
                    f"⏰ Час початку: <b>{now_str}</b>\n\n"
                    f"⚠️ Перейдіть в укриття!"
                )
                logger.warning("Оголошено тривогу в районі!")
            else:
                duration_str = ""
                if self.alarm_start_time:
                    dur_min = int((datetime.now() - self.alarm_start_time).total_seconds() // 60)
                    duration_str = f"\n⏱ Тривалість: ~{dur_min} хв."
                msg = (
                    f"🟢 <b>ВІДБІЙ ПОВІТРЯНОЇ ТРИВОГИ!</b>\n"
                    f"📍 <b>Сарненський район / Рівненщина</b>\n"
                    f"⏰ Час відбою: <b>{now_str}</b>{duration_str}\n\n"
                    f"✅ Небезпека минула."
                )
                logger.info("Відбій тривоги в районі!")

            self.is_alarm_active = current_alarm
            if self.send_to_telegram:
                self.sender._send_text_message(msg, thread_id=self.thread_id)

        # 2. Нові цілі, що летять в район (Dangers)
        for d in data["dangers"]:
            did = str(d["id"])
            if did not in self.seen_danger_ids:
                self.seen_danger_ids.add(did)
                dist_str = f"\n📏 Відстань до Сарн: ~{d['distance_km']} км" if d.get('distance_km') else ""
                ch_str = f" (@{d['channel']})" if d.get('channel') else ""

                msg = (
                    f"🚨 <b>ВИЯВЛЕНО ЦІЛЬ В САРНЕНСЬКОМУ РАЙОНІ!</b>\n\n"
                    f"🎯 <b>Тип:</b> {d['threat_type']}\n"
                    f"📍 <b>Локація / Вектор:</b> {d['place']}{dist_str}\n"
                    f"📝 <b>Деталі:</b> {d.get('text') or '—'}{ch_str}\n"
                    f"⏰ <b>Час:</b> {now_str}\n\n"
                    f"🔗 <a href='https://eradar.app/'>Дивитися на карті eRadar</a>"
                )
                logger.warning(f"Нова ціль для Сарн: {d['threat_type']} -> {d['place']}")
                if self.send_to_telegram:
                    self.sender._send_text_message(msg, thread_id=self.thread_id)

        # 3. Нові моніторингові повідомлення
        for f in data["feed_events"]:
            fid = str(f.get("id"))
            if fid not in self.seen_feed_ids:
                self.seen_feed_ids.add(fid)
                msg = (
                    f"📡 <b>Моніторинг eRadar (Сарненський р-н):</b>\n"
                    f"📢 Джерело: @{f.get('channel', '—')}\n\n"
                    f"💬 <i>{f.get('text', '')}</i>\n"
                    f"⏰ Час: {now_str}"
                )
                logger.info(f"Нове повідомлення моніторингу: {f.get('text')}")
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
    
    # Для постійного відслідковування розкоментуйте:
    # monitor.run_live(poll_interval=15)
