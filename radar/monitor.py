# -*- coding: utf-8 -*-
import time
import logging
from datetime import datetime, timezone
from curl_cffi import requests

from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    THREAD_ID_ALERTS,
)
from telegram_sender import TelegramSender
from radar.utils import (
    SARNY_COMMUNITIES,
    SARNY_LAT,
    SARNY_LNG,
    SARNY_RADIUS_KM,
    format_telegram_html,
    format_duration,
)
from radar.ukrainealarm_client import UkraineAlarmClient

logger = logging.getLogger("RadarMonitor")


class SarnyRadarMonitor:
    """
    Монітор повітряних тривог та загроз через безкоштовний офіційний API map.ukrainealarm.com:
    - Офіційні повітряні тривоги та відбої (Рівненська область, Сарненський район та всі 11 громад).
    - Радарне відстеження повітряних цілей (БпЛА / ракети) у зоні Сарненського району та кожної громади.
    - Сповіщення про зліт МіГ-31К та артилерійську загрозу.
    """

    def __init__(self, send_to_telegram: bool = True, radar_radius_km: float = 75.0):
        self.session = requests.Session()
        self.send_to_telegram = send_to_telegram
        self.sender = TelegramSender(token=TELEGRAM_BOT_TOKEN, channel=TELEGRAM_CHAT_ID)
        self.thread_id = THREAD_ID_ALERTS
        self.radar_radius_km = radar_radius_km

        # Клієнт безкоштовного API map.ukrainealarm.com
        self.client = UkraineAlarmClient(self.session)

        # Стан тривог
        self.is_alarm_active = False
        self.alarm_start_time = None
        self.is_oblast_alarm_active = False
        self.is_district_alarm_active = False

        # Стан по кожній з 11 громад Сарненського району
        self.community_states = {
            comm_id: {"is_alarm": False, "start_time": None, "name": comm_cfg["name"]}
            for comm_id, comm_cfg in SARNY_COMMUNITIES.items()
        }

        # Кеші для уникнення повторів
        self.seen_target_ids = set()
        self.seen_mig_keys = set()
        self.seen_artillery_keys = set()

    def get_thread_for_region(self, region_id: str = "sarny"):
        """Повертає цільовий thread_id для Telegram."""
        return self.thread_id

    def get_status(self) -> dict:
        """Отримує актуальний статус від map.ukrainealarm.com."""
        return self.client.get_status_for_sarny(radar_radius_km=self.radar_radius_km)

    def check_and_notify(self):
        """Опитує API та надсилає сповіщення у разі змін."""
        status = self.get_status()
        now_dt = datetime.now()
        now_str = now_dt.strftime("%H:%M:%S")

        overall_alarm = status["overall_alarm"]
        is_oblast = status["is_oblast_alarm"]
        is_district = status["is_district_alarm"]
        active_comms = status["active_communities"]
        reasons_list = status["reasons"]

        reasons_text = ", ".join(reasons_list) if reasons_list else "Повітряна загроза"
        reasons_block = f"\n🎯 <b>Загроза:</b> {format_telegram_html(reasons_text)}" if reasons_list else ""

        # -------------------------------------------------------------
        # 1. ОБРОБКА ПОВІТРЯНОЇ ТРИВОГИ ТА ВІДБОЮ ДЛЯ САРНЕНСЬКОГО РАЙОНУ
        # -------------------------------------------------------------
        if overall_alarm != self.is_alarm_active:
            if overall_alarm:
                # ОГОЛОШЕНО ТРИВОГУ
                self.alarm_start_time = now_dt
                self.is_oblast_alarm_active = is_oblast
                self.is_district_alarm_active = is_district

                # Формуємо точну локацію оголошення
                if is_oblast:
                    loc_title = "Рівненська область (включаючи Сарненський район та всі громади)"
                    header = "🔴 <b>УВАГА! ПОВІТРЯНА ТРИВОГА ПО ВСІЙ ОБЛАСТІ!</b>"
                elif is_district:
                    loc_title = "Сарненський район (всі підрайони та громади)"
                    header = "🔴 <b>УВАГА! ПОВІТРЯНА ТРИВОГА У САРНЕНСЬКОМУ РАЙОНІ!</b>"
                else:
                    comm_names = [c["name"] for c in active_comms.values()]
                    loc_title = ", ".join(comm_names) + " (Сарненський район)"
                    header = "🔴 <b>УВАГА! ПОВІТРЯНА ТРИВОГА!</b>"

                msg = (
                    f"{header}\n\n"
                    f"📍 <b>Локація:</b> {loc_title}"
                    f"{reasons_block}\n"
                    f"⏰ <b>Час початку:</b> {now_str}\n\n"
                    f"⚠️ Негайно прямуйте в укриття!\n\n"
                    f"📡 <i>Джерело: Мапа тривог України (map.ukrainealarm.com)</i>"
                )
                logger.warning(f"🔴 Оголошено тривогу: {loc_title} ({reasons_text})")

                sent_ok = True
                if self.send_to_telegram:
                    sent_ok = self.sender._send_text_message(msg, thread_id=self.thread_id)

                if sent_ok or not self.send_to_telegram:
                    self.is_alarm_active = True
                else:
                    logger.error("❌ Не вдалося надіслати сповіщення про тривогу в Telegram!")

            else:
                # ВІДБІЙ ТРИВОГИ
                duration_str = ""
                if self.alarm_start_time:
                    dur_sec = (now_dt - self.alarm_start_time).total_seconds()
                    duration_str = f"\n⏱ <b>Тривалість:</b> {format_duration(dur_sec)}"

                loc_title = "Сарненський район та громади"
                msg = (
                    f"🟢 <b>ВІДБІЙ ПОВІТРЯНОЇ ТРИВОГИ!</b>\n\n"
                    f"📍 <b>Локація:</b> {loc_title}\n"
                    f"⏰ <b>Час відбою:</b> {now_str}"
                    f"{duration_str}\n\n"
                    f"✅ Небезпека минула. Слідкуйте за подальшими повідомленнями.\n\n"
                    f"📡 <i>Джерело: Мапа тривог України (map.ukrainealarm.com)</i>"
                )
                logger.info(f"🟢 Відбій тривоги для Сарненського району ({duration_str})")

                sent_ok = True
                if self.send_to_telegram:
                    sent_ok = self.sender._send_text_message(msg, thread_id=self.thread_id)

                if sent_ok or not self.send_to_telegram:
                    self.is_alarm_active = False
                    self.is_oblast_alarm_active = False
                    self.is_district_alarm_active = False
                    self.alarm_start_time = None
                    for c_state in self.community_states.values():
                        c_state["is_alarm"] = False
                        c_state["start_time"] = None
                else:
                    logger.error("❌ Не вдалося надіслати повідомлення про відбій!")

        # -------------------------------------------------------------
        # 2. ДЕТАЛЬНИЙ МОНІТОРИНГ ОКРЕМИХ ГРОМАД (якщо тривога точкова)
        # -------------------------------------------------------------
        if not is_oblast and not is_district and overall_alarm:
            for comm_id, comm_data in active_comms.items():
                c_state = self.community_states[comm_id]
                if not c_state["is_alarm"]:
                    c_state["is_alarm"] = True
                    c_state["start_time"] = now_dt
                    c_reasons = ", ".join(comm_data["reasons"]) if comm_data.get("reasons") else ""
                    c_reasons_block = f"\n🎯 <b>Загроза:</b> {format_telegram_html(c_reasons)}" if c_reasons else ""
                    msg = (
                        f"🔴 <b>УВАГА! ПОВІТРЯНА ТРИВОГА У ГРОМАДІ!</b>\n\n"
                        f"📍 <b>{comm_data['name']}</b> (Сарненський район)"
                        f"{c_reasons_block}\n"
                        f"⏰ <b>Час:</b> {now_str}\n\n"
                        f"⚠️ Перейдіть в укриття!\n"
                        f"📡 <i>Джерело: map.ukrainealarm.com</i>"
                    )
                    logger.warning(f"🔴 Тривога у громаді: {comm_data['name']}")
                    if self.send_to_telegram:
                        self.sender._send_text_message(msg, thread_id=self.thread_id)

        # -------------------------------------------------------------
        # 3. РАДАРНІ ЦІЛІ БІЛЯ САРНЕНСЬКОГО РАЙОНУ (БпЛА / РАКЕТИ)
        # -------------------------------------------------------------
        near_targets = status.get("targets_near_district", [])
        for t in near_targets:
            tid = t["id"]
            if tid in self.seen_target_ids:
                continue

            self.seen_target_ids.add(tid)

            compass_str = f"| Курс: {t['compass']}" if t.get("compass") else ""
            msg = (
                f"🚨 <b>[Мапа тривог / Радар] ЦІЛЬ БІЛЯ САРНЕНСЬКОГО РАЙОНУ!</b>\n\n"
                f"🎯 <b>Загроза:</b> {t['type']}\n"
                f"📍 <b>Найближча громада:</b> {t['closest_community_name']} (~{t['dist_to_closest_comm_km']} км)\n"
                f"🧭 <b>До м. Сарни:</b> ~{t['dist_to_sarny_km']} км {compass_str}\n"
                f"📡 <b>Джерело:</b> {format_telegram_html(t['sources_text'])}\n"
                f"⏰ <b>Час:</b> {now_str}\n\n"
                f"📡 <i>Джерело: Мапа тривог України (map.ukrainealarm.com)</i>"
            )
            logger.warning(f"🚨 Радар: ціль {t['type']} біля {t['closest_community_short']} (~{t['dist_to_closest_comm_km']} км)")
            if self.send_to_telegram:
                self.sender._send_text_message(msg, thread_id=self.thread_id)

        # -------------------------------------------------------------
        # 4. ЗАГРОЗА МіГ-31К (Кинджал)
        # -------------------------------------------------------------
        mig_alerts = status.get("mig_alerts", [])
        for mig in mig_alerts:
            m_key = str(mig)
            if m_key not in self.seen_mig_keys:
                self.seen_mig_keys.add(m_key)
                msg = (
                    f"⚠️ <b>[Мапа тривог] ЗЛІТ МіГ-31К!</b>\n\n"
                    f"🚀 Зафіксовано зліт надзвукового винищувача МіГ-31К!\n"
                    f"🔴 Ракетна небезпека по всій території України (загроза ракет Х-47М2 «Кинджал»)!\n"
                    f"⏰ <b>Час:</b> {now_str}\n\n"
                    f"📡 <i>Джерело: map.ukrainealarm.com</i>"
                )
                logger.warning("⚠️ Зліт МіГ-31К!")
                if self.send_to_telegram:
                    self.sender._send_text_message(msg, thread_id=self.thread_id)

    def run_live(self, poll_interval: int = 10):
        """Запускає постійний моніторинг у реальному часі."""
        logger.info("🛰 Запуск безкоштовного моніторингу map.ukrainealarm.com для Сарн...")
        logger.info(f"   📍 Цільовий Telegram Thread ID: {self.thread_id}")
        logger.info(f"   🎯 Радіус радара: {self.radar_radius_km} км навколо району та громад")
        logger.info(f"   ⏱ Інтервал перевірки: кожні {poll_interval} сек.")
        logger.info(f"   🏘 Громад у моніторингу: {len(SARNY_COMMUNITIES)} (всі підрайони Сарненського району)")

        # Початковий статус
        init_data = self.get_status()
        self.is_alarm_active = init_data["overall_alarm"]
        if self.is_alarm_active:
            self.alarm_start_time = datetime.now()
            self.is_oblast_alarm_active = init_data["is_oblast_alarm"]
            self.is_district_alarm_active = init_data["is_district_alarm"]

        init_status_text = "🔴 ПОВІТРЯНА ТРИВОГА" if self.is_alarm_active else "🟢 ВІДБІЙ"
        logger.info(f"   Поточний статус Сарненського району: {init_status_text}")

        # Пре-сідінг цілей при першому старті (щоб не надсилати старі цілі)
        for t in init_data.get("targets", []):
            self.seen_target_ids.add(t["id"])

        for mig in init_data.get("mig_alerts", []):
            self.seen_mig_keys.add(str(mig))

        logger.info(f"🛡 Пре-сідінг завершено (цілей на карті: {len(init_data.get('targets', []))}). Спаму при старті не буде!")

        while True:
            try:
                self.check_and_notify()
            except Exception as e:
                logger.error(f"Помилка циклу моніторингу map.ukrainealarm.com: {e}", exc_info=True)
            time.sleep(poll_interval)
