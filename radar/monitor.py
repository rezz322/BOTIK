# -*- coding: utf-8 -*-
import time
import logging
from datetime import datetime, timezone
from curl_cffi import requests

from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    THREAD_ID_ALERTS,
    KUPOL_MODE,
    ERADAR_MODE,
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
    Монітор повітряних загроз та тривог:
    - eRadar (eradar.app): активні загрози, моніторинговий фід, офіційний статус тривоги.
    - КУПОЛ (kupol.in.ua / NEPTUN): відстеження активних цілей (БпЛА, ракети, КАБ, FPV) по всій Україні або в районі Сарн.
    - Надійна перевірка тривоги та відбою з гарантованим сповіщенням.
    """

    def __init__(self, send_to_telegram: bool = True):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json",
        })
        self.send_to_telegram = send_to_telegram
        self.sender = TelegramSender(token=TELEGRAM_BOT_TOKEN, channel=TELEGRAM_CHAT_ID)

        # Режим роботи КУПОЛ: 'all_ukraine' (вся Україна) або 'sarny' (тільки Сарни)
        self.kupol_mode = KUPOL_MODE
        self.eradar_mode = ERADAR_MODE

        # Конфігурація регіонів
        self.regions = MONITORED_REGIONS

        # Прив'язка цільових гілок Telegram
        self.region_threads = {
            "sarny": THREAD_ID_ALERTS,
        }

        # Для зворотної сумісності
        self.thread_id = THREAD_ID_ALERTS

        # Клієнти сервісів
        self.eradar = ERadarClient(self.session)
        self.kupol = KupolClient(self.session)
        self.alerts = AlertsClient(self.session, eradar_client=self.eradar, kupol_client=self.kupol)

        # Статуси тривог по регіонах
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
        Отримує повну актуальну інформацію з eRadar та КУПОЛ:
        1. Статуси тривог по регіонах (консенсус eRadar + КУПОЛ + alerts.in.ua)
        2. Активні цілі eRadar (Dangers)
        3. Повідомлення моніторингу eRadar (Feed)
        4. Активні цілі КУПОЛ (NEPTUN) згідно з KUPOL_MODE (вся Україна або Сарни)
        """
        alarms_by_region = self.alerts.check_alarms_for_regions(self.regions)
        dangers_by_region, danger_feed_ids, danger_message_keys = self.eradar.get_dangers_for_regions(self.regions)
        feed_by_region = self.eradar.get_feed_for_regions(danger_feed_ids, danger_message_keys, self.regions)

        # Отримуємо цілі КУПОЛ згідно з активним режимом
        kupol_threats = self.kupol.get_threats(mode=self.kupol_mode, regions=self.regions)
        kupol_by_region = self.kupol.get_threats_for_regions(self.regions, mode=self.kupol_mode)

        all_dangers = []
        for d_list in dangers_by_region.values():
            all_dangers.extend(d_list)

        all_feed = []
        for f_list in feed_by_region.values():
            all_feed.extend(f_list)

        sarny_alarm = alarms_by_region.get("sarny", False)

        return {
            "is_alarm": sarny_alarm,
            "alarm_text": "🔴 ПОВІТРЯНА ТРИВОГА" if sarny_alarm else "🟢 ВІДБІЙ",
            "alarms_by_region": alarms_by_region,
            "dangers_by_region": dangers_by_region,
            "feed_by_region": feed_by_region,
            "kupol_by_region": kupol_by_region,
            "kupol_threats": kupol_threats,
            "dangers": all_dangers,
            "feed_events": all_feed,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }

    def check_and_notify(self):
        """Перевіряє зміни по всіх джерелах та надсилає сповіщення у відповідні гілки."""
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
                    logger.warning(f"🔴 Оголошено тривогу: {r_cfg['name']}!")
                else:
                    duration_str = ""
                    if state.get("start_time"):
                        dur_sec = (datetime.now() - state["start_time"]).total_seconds()
                        duration_str = f"\n⏱ <b>Тривалість:</b> {format_duration(dur_sec)}"
                    msg = (
                        f"🟢 <b>ВІДБІЙ ПОВІТРЯНОЇ ТРИВОГИ!</b>\n\n"
                        f"📍 <b>{r_cfg['name']}</b>\n"
                        f"⏰ <b>Час відбою:</b> {now_str}"
                        f"{duration_str}\n\n"
                        f"✅ Небезпека минула."
                    )
                    logger.info(f"🟢 Відбій тривоги: {r_cfg['name']}!")

                sent_ok = True
                if self.send_to_telegram:
                    sent_ok = self.sender._send_text_message(msg, thread_id=target_thread)

                # Оновлюємо стан тільки якщо повідомлення було успішно надіслано
                if sent_ok or not self.send_to_telegram:
                    state["is_alarm"] = current_alarm
                    if r_id == "sarny":
                        self.is_alarm_active = current_alarm
                else:
                    logger.error(f"❌ Не вдалося надіслати повідомлення про {'тривогу' if current_alarm else 'відбій'}! Стан залишено для повтору.")

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

        # 4. Нові цілі від сервісу КУПОЛ (kupol.in.ua / NEPTUN)
        kupol_threats = data.get("kupol_threats", [])
        kupol_thread = self.get_thread_for_region("sarny")

        for th in kupol_threats:
            kid = str(th["id"])
            raw_id = str(th.get("raw_id", kid))

            if kid in self.seen_kupol_ids or raw_id in self.seen_kupol_ids:
                continue

            self.seen_kupol_ids.add(kid)
            self.seen_kupol_ids.add(raw_id)

            dist_str = f" (~{th['distance_km']} км від Сарн)" if th.get("distance_km") else ""
            location_str = th.get("location") or th.get("region") or "Україна"

            course_block = f"\n🧭 <b>Курс:</b> {th['course_desc']}" if th.get("course_desc") else ""
            speed_block = f"\n💨 <b>Швидкість:</b> ~{round(th['speed_kmh'])} км/год" if th.get("speed_kmh") else ""

            note_block = ""
            if th.get("note"):
                clean_note = clean_text_line(th["note"])
                note_html = format_telegram_html(clean_note)
                note_block = f"\n💬 <b>Інформація:</b> {note_html}"

            # Заголовок: якщо близько до Сарн — небезпека для району, якщо по Україні — моніторинг цілі
            if th.get("is_near_sarny"):
                header = "🚨 <b>[КУПОЛ / NEPTUN] УВАГА! ЦІЛЬ БІЛЯ САРНЕНСЬКОГО РАЙОНУ!</b>"
            elif self.kupol_mode == "all_ukraine":
                header = "🛡 <b>[КУПОЛ / NEPTUN] АКТИВНА ЦІЛЬ В УКРАЇНІ</b>"
            else:
                header = "🛡 <b>[КУПОЛ / NEPTUN] ЗАГРОЗА ДЛЯ РАЙОНУ!</b>"

            msg = (
                f"{header}\n\n"
                f"📍 <b>Локація:</b> {location_str}{dist_str}\n"
                f"🎯 <b>Загроза:</b> {th['threat_type']}"
                f"{course_block}"
                f"{speed_block}"
                f"{note_block}\n"
                f"⏰ <b>Час:</b> {now_str}\n\n"
                f"📡 <i>Джерело: КУПОЛ (kupol.in.ua)</i>"
            )
            logger.warning(f"[КУПОЛ] Нова ціль ({th['threat_type']}): {location_str}{dist_str}")
            if self.send_to_telegram:
                self.sender._send_text_message(msg, thread_id=kupol_thread)

    def run_live(self, poll_interval: int = 15):
        """Запускає постійний моніторинг у реальному часі."""
        mode_str = "ВСЯ УКРАЇНА" if self.kupol_mode == "all_ukraine" else "ТІЛЬКИ САРНИ"
        logger.info(f"🛰 Запуск живого моніторингу eRadar + КУПОЛ...")
        logger.info(f"   ⚙️ Режим КУПОЛ: [{mode_str}] (KUPOL_MODE={self.kupol_mode})")
        for r_id, r_cfg in self.regions.items():
            th_id = self.get_thread_for_region(r_id)
            logger.info(f"   📍 Регіон тривог: {r_cfg['name']} -> Telegram Thread ID: {th_id}")
        logger.info(f"⏱ Інтервал перевірки: кожні {poll_interval} сек.")

        init_data = self.get_status()
        for r_id, r_cfg in self.regions.items():
            alarm_on = init_data["alarms_by_region"].get(r_id, False)
            self.alarm_states[r_id]["is_alarm"] = alarm_on
            if alarm_on:
                self.alarm_states[r_id]["start_time"] = datetime.now()
            alarm_text = "🔴 ПОВІТРЯНА ТРИВОГА" if alarm_on else "🟢 ВІДБІЙ"
            e_count = len(init_data["dangers_by_region"].get(r_id, []))
            k_count = len(init_data.get("kupol_threats", []))
            logger.info(f"   [{r_cfg['short_name']}] Тривога: {alarm_text} | Цілей eRadar: {e_count}, КУПОЛ: {k_count}")

        # Прогрів (пре-сідінг): запам'ятовуємо вже наявні цілі при старті, щоб не спамити старими подіями
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

        for th in init_data.get("kupol_threats", []):
            self.seen_kupol_ids.add(str(th["id"]))
            if th.get("raw_id"):
                self.seen_kupol_ids.add(str(th["raw_id"]))

        logger.info(
            f"🛡 Пре-сідінг завершено: збережено {len(self.seen_feed_ids)} постів eRadar "
            f"та {len(self.seen_kupol_ids)} цілей КУПОЛ. Спаму при старті не буде!"
        )

        while True:
            try:
                self.check_and_notify()
            except Exception as e:
                logger.error(f"Помилка циклу моніторингу: {e}", exc_info=True)
            time.sleep(poll_interval)
