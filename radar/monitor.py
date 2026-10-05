import time
import logging
from datetime import datetime, timezone
from curl_cffi import requests

from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    THREAD_ID_ALERTS,
    THREAD_ID_ALERTS_ODESA,
    THREAD_ID_ALERTS_KORYUKIVKA,
)
from telegram_sender import TelegramSender
from radar.utils import (
    MONITORED_REGIONS,
    format_telegram_html,
    format_duration,
    clean_text_line,
)
from radar.eradar_client import ERadarClient
from radar.kupol_client import KupolClient
from radar.alerts_client import AlertsClient

logger = logging.getLogger("RadarMonitor")


class SarnyRadarMonitor:
    """
    Монітор повітряних загроз для кількох регіонів (Сарненський район, Одеса, Корюківка):
    - Отримує дані від eRadar (eradar.app) та КУПОЛ (kupol.in.ua / NEPTUN).
    - Перевіряє статус тривоги (alerts.in.ua + бекапи) окремо для кожного регіону.
    - Відправляє повідомлення у Telegram із чітким маркуванням сервісу та регіону.
    """

    def __init__(self, send_to_telegram: bool = True):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json",
        })
        self.send_to_telegram = send_to_telegram
        self.sender = TelegramSender(token=TELEGRAM_BOT_TOKEN, channel=TELEGRAM_CHAT_ID)

        # Конфігурація регіонів
        self.regions = MONITORED_REGIONS

        # Прив'язка цільових гілок Telegram до кожного регіону
        self.region_threads = {
            "sarny": THREAD_ID_ALERTS,
            "odesa": THREAD_ID_ALERTS_ODESA or THREAD_ID_ALERTS,
            "koryukivka": THREAD_ID_ALERTS_KORYUKIVKA or THREAD_ID_ALERTS,
        }

        # Для зворотної сумісності
        self.thread_id = THREAD_ID_ALERTS

        # Клієнти сервісів
        self.eradar = ERadarClient(self.session)
        self.kupol = KupolClient(self.session)
        self.alerts = AlertsClient(self.session, eradar_client=self.eradar, kupol_client=self.kupol)

        # Статуси тривог по регіонах: { 'sarny': {'is_alarm': False, 'start_time': None}, ... }
        self.alarm_states = {
            r_id: {"is_alarm": False, "start_time": None}
            for r_id in self.regions
        }

        # Зворотна сумісність
        self.is_alarm_active = False
        self.alarm_start_time = None

        # Запобігання повторним повідомленням
        self.seen_danger_ids = set()
        self.seen_feed_ids = set()
        self.seen_message_keys = set()
        self.seen_kupol_ids = set()

    def get_thread_for_region(self, region_id: str):
        """Отримує thread_id для відправки повідомлень по регіону."""
        return self.region_threads.get(region_id, self.thread_id)

    def get_status(self) -> dict:
        """
        Отримує повну актуальну інформацію з eRadar та КУПОЛ для всіх регіонів (Сарни + Одеса):
        1. Статуси тривог по регіонах
        2. Активні цілі eRadar (Dangers)
        3. Повідомлення моніторингу eRadar (Feed)
        4. Активні цілі КУПОЛ (NEPTUN) з курсом та координатами
        """
        alarms_by_region = self.alerts.check_alarms_for_regions(self.regions)
        dangers_by_region, danger_feed_ids, danger_message_keys = self.eradar.get_dangers_for_regions(self.regions)
        feed_by_region = self.eradar.get_feed_for_regions(danger_feed_ids, danger_message_keys, self.regions)
        kupol_by_region = self.kupol.get_threats_for_regions(self.regions)

        all_dangers = []
        for d_list in dangers_by_region.values():
            all_dangers.extend(d_list)

        all_feed = []
        for f_list in feed_by_region.values():
            all_feed.extend(f_list)

        all_kupol = []
        for k_list in kupol_by_region.values():
            all_kupol.extend(k_list)

        # Статус для Сарн (зворотна сумісність)
        sarny_alarm = alarms_by_region.get("sarny", False)

        return {
            "is_alarm": sarny_alarm,
            "alarm_text": "🔴 ПОВІТРЯНА ТРИВОГА" if sarny_alarm else "🟢 ВІДБІЙ",
            "alarms_by_region": alarms_by_region,
            "dangers_by_region": dangers_by_region,
            "feed_by_region": feed_by_region,
            "kupol_by_region": kupol_by_region,
            "dangers": all_dangers,
            "feed_events": all_feed,
            "kupol_threats": all_kupol,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def check_and_notify(self):
        """Перевіряє зміни по всіх регіонах та надсилає сповіщення у відповідні гілки."""
        data = self.get_status()
        now_str = datetime.now().strftime("%H:%M:%S")

        # 1. Зміна статусу тривоги для кожного регіону окремо
        for r_id, r_cfg in self.regions.items():
            current_alarm = data["alarms_by_region"].get(r_id, False)
            state = self.alarm_states[r_id]
            target_thread = self.get_thread_for_region(r_id)

            if current_alarm != state["is_alarm"]:
                if current_alarm:
                    state["start_time"] = datetime.now()
                    msg = (
                        f"🔴 <b>УВАГА! ПОВІТРЯНА ТРИВОГА!</b>\n\n"
                        f"📍 <b>{r_cfg['name']}</b>\n"
                        f"⏰ <b>Час початку:</b> {now_str}\n\n"
                        f"⚠️ Перейдіть в укриття!"
                    )
                    logger.warning(f"Оголошено тривогу: {r_cfg['name']}!")
                else:
                    duration_str = ""
                    if state["start_time"]:
                        dur_sec = (datetime.now() - state["start_time"]).total_seconds()
                        duration_str = f"\n⏱ <b>Тривалість:</b> {format_duration(dur_sec)}"
                    msg = (
                        f"🟢 <b>ВІДБІЙ ПОВІТРЯНОЇ ТРИВОГИ!</b>\n\n"
                        f"📍 <b>{r_cfg['name']}</b>\n"
                        f"⏰ <b>Час відбою:</b> {now_str}"
                        f"{duration_str}\n\n"
                        f"✅ Небезпека минула."
                    )
                    logger.info(f"Відбій тривоги: {r_cfg['name']}!")

                state["is_alarm"] = current_alarm
                if r_id == "sarny":
                    self.is_alarm_active = current_alarm

                if self.send_to_telegram:
                    self.sender._send_text_message(msg, thread_id=target_thread)

        # 2. Нові цілі від основного сервісу eRadar (Dangers)
        for r_id, d_list in data["dangers_by_region"].items():
            r_cfg = self.regions[r_id]
            target_thread = self.get_thread_for_region(r_id)

            for d in d_list:
                did = str(d["id"])
                last_msg_id = str(d["last_message_id"]) if d.get("last_message_id") else None
                msg_key = f"{d.get('channel')}_{d.get('tg_message_id')}" if d.get("channel") and d.get("tg_message_id") else None

                if last_msg_id:
                    self.seen_feed_ids.add(last_msg_id)
                if msg_key:
                    self.seen_message_keys.add(msg_key)

                if did not in self.seen_danger_ids:
                    self.seen_danger_ids.add(did)

                    dist_str = f" (~{d['distance_km']} км від {r_cfg['short_name']})" if d.get('distance_km') else ""
                    place_text = format_telegram_html(d.get("place") or "")
                    vector_info = f"{place_text}{dist_str}" if place_text else r_cfg["name"]

                    det_text = (d.get('text') or '').strip()
                    fly_info_block = ""
                    if det_text and det_text != '—':
                        det_html = format_telegram_html(det_text)
                        fly_info_block = f"\n🧭 <b>Куди летить:</b>\n{det_html}"

                    msg = (
                        f"🚨 <b>[eRadar] ЗАГРОЗА ДЛЯ РАЙОНУ!</b>\n\n"
                        f"📍 <b>Регіон:</b> {r_cfg['name']}\n"
                        f"🎯 <b>Загроза:</b> {d['threat_type']}\n"
                        f"📍 <b>Вектор:</b> {vector_info}"
                        f"{fly_info_block}\n"
                        f"⏰ <b>Час:</b> {now_str}\n\n"
                        f"📡 <i>Джерело: eRadar.app</i>"
                    )
                    logger.warning(f"[eRadar] Нова ціль для {r_cfg['short_name']}: {d['threat_type']} -> {d['place']}")
                    if self.send_to_telegram:
                        self.sender._send_text_message(msg, thread_id=target_thread)

        # 3. Нові моніторингові повідомлення eRadar (Feed)
        for r_id, f_list in data["feed_by_region"].items():
            r_cfg = self.regions[r_id]
            target_thread = self.get_thread_for_region(r_id)

            for f in f_list:
                fid = str(f.get("id"))
                feed_item_key = f"{fid}_{r_id}"
                msg_key = f"{f.get('channel')}_{f.get('tg_message_id')}_{r_id}" if f.get("channel") and f.get("tg_message_id") else None

                if feed_item_key in self.seen_feed_ids or (msg_key and msg_key in self.seen_message_keys):
                    continue

                self.seen_feed_ids.add(feed_item_key)
                if msg_key:
                    self.seen_message_keys.add(msg_key)

                text_to_show = f.get("filtered_text") or ""
                if not text_to_show:
                    continue

                text_html = format_telegram_html(text_to_show)

                msg = (
                    f"📡 <b>[eRadar Моніторинг] {r_cfg['name']}:</b>\n\n"
                    f"💬 <i>{text_html}</i>\n\n"
                    f"⏰ <b>Час:</b> {now_str}\n\n"
                    f"📡 <i>Джерело: eRadar Feed</i>"
                )
                logger.info(f"[eRadar Feed] {r_cfg['short_name']}: {text_to_show}")
                if self.send_to_telegram:
                    self.sender._send_text_message(msg, thread_id=target_thread)

        # 4. Нові цілі від додаткового сервісу КУПОЛ (kupol.in.ua / NEPTUN)
        for r_id, k_list in data["kupol_by_region"].items():
            r_cfg = self.regions[r_id]
            target_thread = self.get_thread_for_region(r_id)

            for th in k_list:
                kid = str(th["id"])
                if kid not in self.seen_kupol_ids:
                    self.seen_kupol_ids.add(kid)

                    dist_str = f" (~{th['distance_km']} км від {r_cfg['short_name']})" if th.get("distance_km") else ""
                    region_str = f"{th['region']}" if th.get("region") else r_cfg["name"]
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
                        f"📍 <b>Регіон:</b> {r_cfg['name']}\n"
                        f"🎯 <b>Загроза:</b> {th['threat_type']}\n"
                        f"📍 <b>Локація:</b> {loc_info}"
                        f"{course_block}"
                        f"{note_block}\n"
                        f"⏰ <b>Час:</b> {now_str}\n\n"
                        f"📡 <i>Джерело: КУПОЛ (kupol.in.ua)</i>"
                    )
                    logger.warning(f"[КУПОЛ] Нова ціль для {r_cfg['short_name']}: {th['threat_type']} -> {th.get('note')}")
                    if self.send_to_telegram:
                        self.sender._send_text_message(msg, thread_id=target_thread)

    def run_live(self, poll_interval: int = 15):
        """Запускає постійний моніторинг у реальному часі."""
        logger.info("🛰 Запуск живого моніторингу eRadar + КУПОЛ для регіонів: Сарни, Одеса...")
        for r_id, r_cfg in self.regions.items():
            th_id = self.get_thread_for_region(r_id)
            logger.info(f"   📍 {r_cfg['name']} -> Thread ID: {th_id}")
        logger.info(f"⏱ Інтервал перевірки: кожні {poll_interval} сек.")

        init_data = self.get_status()
        for r_id, r_cfg in self.regions.items():
            alarm_on = init_data["alarms_by_region"].get(r_id, False)
            self.alarm_states[r_id]["is_alarm"] = alarm_on
            alarm_text = "🔴 ПОВІТРЯНА ТРИВОГА" if alarm_on else "🟢 ВІДБІЙ"
            e_count = len(init_data["dangers_by_region"].get(r_id, []))
            k_count = len(init_data["kupol_by_region"].get(r_id, []))
            logger.info(f"   [{r_cfg['short_name']}] Тривога: {alarm_text} | Цілей eRadar: {e_count}, КУПОЛ: {k_count}")

        # Прогрів (пре-сідінг): запам'ятовуємо всю наявну історію, щоб не спамити старими постами при старті
        for d in init_data["dangers"]:
            self.seen_danger_ids.add(str(d["id"]))
            if d.get("last_message_id"):
                self.seen_feed_ids.add(str(d["last_message_id"]))
            if d.get("channel") and d.get("tg_message_id"):
                self.seen_message_keys.add(f"{d['channel']}_{d['tg_message_id']}")

        for f in init_data["feed_events"]:
            fid = str(f.get("id"))
            r_id = f.get("region_id", "")
            self.seen_feed_ids.add(fid)
            self.seen_feed_ids.add(f"{fid}_{r_id}")
            if f.get("channel") and f.get("tg_message_id"):
                self.seen_message_keys.add(f"{f['channel']}_{f['tg_message_id']}")
                self.seen_message_keys.add(f"{f['channel']}_{f['tg_message_id']}_{r_id}")

        for th in init_data["kupol_threats"]:
            self.seen_kupol_ids.add(str(th["id"]))
            if th.get("raw_id"):
                self.seen_kupol_ids.add(str(th["raw_id"]))

        logger.info(f"🛡 Пре-сідінг завершено: збережено {len(self.seen_feed_ids)} постів та {len(self.seen_kupol_ids)} цілей. Спаму не буде!")

        while True:
            try:
                self.check_and_notify()
            except Exception as e:
                logger.error(f"Помилка циклу моніторингу: {e}")
            time.sleep(poll_interval)
