import time
import logging
from datetime import datetime, timezone
from curl_cffi import requests

from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, THREAD_ID_ALERTS
from telegram_sender import TelegramSender
from radar.utils import (
    format_telegram_html,
    format_duration,
    clean_text_line,
    filter_relevant_lines,
)
from radar.eradar_client import ERadarClient
from radar.kupol_client import KupolClient
from radar.alerts_client import AlertsClient

logger = logging.getLogger("SarnyRadarMonitor")


class SarnyRadarMonitor:
    """
    Головний монітор загроз для Сарненського району:
    - Об'єднує джерела eRadar (eradar.app) та КУПОЛ (kupol.in.ua / NEPTUN).
    - Перевіряє статус тривоги (alerts.in.ua + бекапи).
    - Відправляє повідомлення у Telegram із чітким маркуванням сервісу-джерела.
    """

    def __init__(self, send_to_telegram: bool = True):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json",
        })
        self.send_to_telegram = send_to_telegram
        self.sender = TelegramSender(token=TELEGRAM_BOT_TOKEN, channel=TELEGRAM_CHAT_ID)
        self.thread_id = THREAD_ID_ALERTS

        # Клієнти окремих сервісів
        self.eradar = ERadarClient(self.session)
        self.kupol = KupolClient(self.session)
        self.alerts = AlertsClient(self.session, eradar_client=self.eradar, kupol_client=self.kupol)

        self.is_alarm_active = False
        self.alarm_start_time = None
        self.seen_danger_ids = set()
        self.seen_feed_ids = set()
        self.seen_message_keys = set()
        self.seen_kupol_ids = set()

    def get_status(self) -> dict:
        """
        Отримує повну актуальну інформацію з eRadar та КУПОЛ для Сарненського району:
        1. Статус тривоги району
        2. Активні цілі eRadar (Dangers)
        3. Повідомлення моніторингу eRadar (Feed)
        4. Активні цілі КУПОЛ (NEPTUN) з курсом та координатами
        """
        is_sarny = self.alerts.check_sarny_alarm()
        dangers, danger_feed_ids, danger_message_keys = self.eradar.get_dangers_for_sarny()
        feed_events = self.eradar.get_feed_for_sarny(danger_feed_ids, danger_message_keys)
        kupol_threats = self.kupol.get_threats_for_sarny()

        return {
            "is_alarm": is_sarny,
            "alarm_text": "🔴 ПОВІТРЯНА ТРИВОГА" if is_sarny else "🟢 ВІДБІЙ",
            "dangers": dangers,
            "feed_events": feed_events,
            "kupol_threats": kupol_threats,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def check_and_notify(self):
        """Перевіряє зміни та надсилає сповіщення при появі загроз чи зміні тривоги у гілку 'Тривога'."""
        data = self.get_status()
        current_alarm = data["is_alarm"]
        now_str = datetime.now().strftime("%H:%M:%S")

        # 1. Зміна статусу тривоги (Початок / Відбій)
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

            if last_msg_id:
                self.seen_feed_ids.add(last_msg_id)
            if msg_key:
                self.seen_message_keys.add(msg_key)

            if did not in self.seen_danger_ids:
                self.seen_danger_ids.add(did)

                dist_str = f" (~{d['distance_km']} км)" if d.get('distance_km') else ""
                place_text = format_telegram_html(d.get("place") or "")
                vector_info = f"{place_text}{dist_str}" if place_text else "Сарненський район"

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
