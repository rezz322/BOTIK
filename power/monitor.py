# -*- coding: utf-8 -*-
import os
import sys
import re
import json
import time
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional, Set, Tuple

from config import (
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    THREAD_ID_POWER,
    POWER_POLL_INTERVAL,
    POWER_WARN_MINUTES,
    POWER_TARGET_SUBQUEUES,
    SEND_INITIAL_POWER,
    POWER_STATE_FILE,
)
from telegram_sender import TelegramSender
from power.client import RivneoblenergoClient, ROE_OBLAST_QUEUES_PDF

logger = logging.getLogger("PowerMonitor")


def parse_intervals(text: str, date_str: str) -> List[Tuple[str, str, datetime, datetime, str]]:
    """
    Парсить діапазони годин із тексту (наприклад: '10:00 - 14:00' або '10:00-14:00, 18:00-22:00').
    Повертає список кортежів: (start_str, end_str, start_dt, end_dt, duration_str)
    """
    matches = re.findall(r"(\d{1,2}:\d{2})\s*[-–—]\s*(\d{1,2}:\d{2})", text or "")
    results = []
    for s_str, e_str in matches:
        try:
            start_dt = datetime.strptime(f"{date_str} {s_str}", "%d.%m.%Y %H:%M")
            end_dt = datetime.strptime(f"{date_str} {e_str}", "%d.%m.%Y %H:%M")
            if end_dt <= start_dt:
                # Якщо закінчення після опівночі
                end_dt += timedelta(days=1)
            duration_sec = (end_dt - start_dt).total_seconds()
            hours = int(duration_sec // 3600)
            mins = int((duration_sec % 3600) // 60)
            dur_str = f"{hours}:{mins:02d} ч."
            results.append((s_str, e_str, start_dt, end_dt, dur_str))
        except Exception as e:
            logger.debug(f"Помилка парсингу діапазону {s_str}-{e_str}: {e}")
    return results


def format_schedule_duration(total_sec: float) -> str:
    """Форматує тривалість для графіка: наприклад '2 год.' або '3:30 год.'"""
    hours = int(total_sec // 3600)
    mins = int((total_sec % 3600) // 60)
    if mins == 0:
        return f"{hours} год."
    return f"{hours}:{mins:02d} год."


class SarnyPowerMonitor:
    """
    Воркер для моніторингу графіків відключень електроенергії (ГПВ)
    по місту Сарни та Сарненському району від офіційного оператора
    ПрАТ «Рівнеобленерго».

    Підтримує:
    1. Попередження з часом відключення за 10 хвилин до початку черги відключення (POWER_WARN_MINUTES).
    2. Публікацію повного оновленого графіка при публікації або коригуванні диспетчером.
    """

    def __init__(
        self,
        send_to_telegram: bool = True,
        thread_id: Optional[int] = THREAD_ID_POWER,
        poll_interval: int = POWER_POLL_INTERVAL,
        warn_minutes: int = POWER_WARN_MINUTES,
        state_file: str = POWER_STATE_FILE,
    ):
        self.send_to_telegram = send_to_telegram
        self.thread_id = thread_id
        self.poll_interval = poll_interval
        self.warn_minutes = warn_minutes
        self.state_file = state_file

        self.client = RivneoblenergoClient()
        self.sender = TelegramSender(token=TELEGRAM_BOT_TOKEN, channel=TELEGRAM_CHAT_ID)

        # Фільтр підчерг (якщо задано в .env, наприклад '1.1,1.2' або 'all')
        self.target_subqueues: Optional[Set[str]] = None
        if POWER_TARGET_SUBQUEUES and POWER_TARGET_SUBQUEUES.lower() != "all":
            self.target_subqueues = {
                sq.strip() for sq in POWER_TARGET_SUBQUEUES.split(",") if sq.strip()
            }

        self.state = self._load_state()
        self.sent_events: Set[str] = set(self.state.get("sent_events", []))
        self.sent_schedules: Set[str] = set(self.state.get("sent_schedules", []))
        self.startup_sent: Set[str] = set()
        self.cached_days: List[Dict[str, Any]] = []

    def _load_state(self) -> Dict[str, Any]:
        """Завантажує збережений стан із JSON-файлу."""
        state = {
            "last_hash": None,
            "days_states": {},
            "initial_sent": False,
            "sent_schedules": [],
            "sent_events": [],
        }
        if os.path.exists(self.state_file):
            try:
                with open(self.state_file, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                    if isinstance(loaded, dict):
                        state.update(loaded)
            except Exception as e:
                logger.warning(f"Не вдалося прочитати {self.state_file}: {e}")

        if not isinstance(state.get("days_states"), dict):
            state["days_states"] = {}
        if not isinstance(state.get("sent_events"), list):
            state["sent_events"] = []
        if not isinstance(state.get("sent_schedules"), list):
            state["sent_schedules"] = []
        return state

    def _save_state(self):
        """Зберігає поточний стан у JSON-файл."""
        try:
            # Зберігаємо не більше останніх подій щоб файл не розростався
            self.state["sent_events"] = list(self.sent_events)[-300:]
            self.state["sent_schedules"] = list(self.sent_schedules)[-30:]
            with open(self.state_file, "w", encoding="utf-8") as f:
                json.dump(self.state, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Помилка збереження стану в {self.state_file}: {e}")

    def format_schedule_message(
        self,
        day_data: Dict[str, Any],
        title_prefix: Optional[str] = None,
    ) -> str:
        """
        Формує повідомлення з графіком відключень у стилі:
        📈 Графік відключень на 17.10.2026

        ⚡️Черга 1.1 відключення
        15:30-19:00 (3:30 год.)
        ⏳ усього не буде 💡 3:30 год.
        """
        date_str = day_data.get("date", "")
        status_by_sq = day_data.get("status_by_subqueue", {})
        has_outages = day_data.get("has_outages", False)
        is_pending = day_data.get("is_pending", False)

        header = title_prefix or f"📈 <b>Графік відключень на {date_str}</b>"
        lines = [header, ""]

        if is_pending:
            lines.append("⏳ <i>Очікується оприлюднення точних годин від диспетчера НЕК «Укренерго».</i>")
        elif not has_outages:
            lines.append("🟢 <b>Відключень за графіком не заплановано.</b> Енергосистема працює стабільно.")
        else:
            for sq, interval_text in sorted(status_by_sq.items()):
                is_selected = self.target_subqueues is None or sq in self.target_subqueues
                if not is_selected:
                    continue

                intervals = parse_intervals(interval_text, date_str)
                if intervals:
                    total_dur_sec = sum(
                        (end_dt - start_dt).total_seconds() for _, _, start_dt, end_dt, _ in intervals
                    )
                    total_dur_str = format_schedule_duration(total_dur_sec)

                    lines.append(f"⚡️Черга {sq} відключення")
                    for s_str, e_str, start_dt, end_dt, _ in intervals:
                        dur_sec = (end_dt - start_dt).total_seconds()
                        dur_single_str = format_schedule_duration(dur_sec)
                        lines.append(f"{s_str}-{e_str} ({dur_single_str})")
                    lines.append(f"⏳ усього не буде 💡 {total_dur_str}\n")
                elif interval_text == "Очікується":
                    lines.append(f"⚡️Черга {sq}")
                    lines.append("⏳ Очікується\n")
                else:
                    lines.append(f"⚡️Черга {sq}")
                    lines.append("🟢 Без обмежень\n")

        return "\n".join(lines).strip()

    def check_timeline_events(self, days: List[Dict[str, Any]]):
        """
        Перевіряє часову шкалу поточного розкладу відключень:
        Надсилає сповіщення за 10 хвилин до початку відключення у стилі:
        🆘ВІДКЛЮЧЕННЯ СВІТЛА ГРУПА 3.1:🆘
        Стабілізаційне відключення (Згідно графіку погодинних відключень)
        Відключення з: 10:11 17.10.2026
        Відключення до: 12:00 17.10.2026
        🤷 Виходить, відключили на 1:49 ч.
        """
        now = datetime.now()
        warn_groups: Dict[Tuple[str, str, str, str], List[str]] = {}

        for day in days:
            d_date = day.get("date", "")
            status_by_sq = day.get("status_by_subqueue", {})

            for sq, interval_text in status_by_sq.items():
                if self.target_subqueues and sq not in self.target_subqueues:
                    continue

                intervals = parse_intervals(interval_text, d_date)
                for s_str, e_str, start_dt, end_dt, dur_str in intervals:
                    key_warn = f"warn_{d_date}_{sq}_{s_str}"

                    diff_start = (start_dt - now).total_seconds()
                    grp_key = (d_date, s_str, e_str, dur_str)

                    # Попередження за 10 хвилин до початку відключення (або менше, до 0 сек)
                    if 0 <= diff_start <= (self.warn_minutes * 60):
                        if key_warn not in self.sent_events:
                            warn_groups.setdefault(grp_key, []).append(sq)
                            self.sent_events.add(key_warn)

        # ----------------- НАДСИЛАННЯ ПОВІДОМЛЕНЬ -----------------

        for (d_date, s_str, e_str, dur_str), sq_list in warn_groups.items():
            sq_text = ", ".join(sorted(sq_list))
            label = "ГРУПА" if len(sq_list) == 1 else "ГРУПИ"
            msg = (
                f"🆘<b>ВІДКЛЮЧЕННЯ СВІТЛА {label} {sq_text}:</b>🆘\n"
                f"Стабілізаційне відключення (Згідно графіку погодинних відключень)\n"
                f"Відключення з: {s_str} {d_date}\n"
                f"Відключення до: {e_str} {d_date}\n"
                f"🤷 Виходить, відключили на {dur_str}"
            )
            logger.info(f"📢 Попередження за {self.warn_minutes} хв для {label.lower()} {sq_text} ({s_str}-{e_str})")
            if self.send_to_telegram:
                self.sender._send_text_message(msg, thread_id=self.thread_id)

        if warn_groups:
            self._save_state()

    def check_and_notify(self, is_startup: bool = False):
        """Опитує сайт Рівнеобленерго та публікує графіки і сповіщення за 10 хв."""
        tag = "[Перший старт] " if is_startup else ""
        logger.info(f"🔍 {tag}Перевірка графіків відключень Рівнеобленерго для Сарн...")
        sys.stdout.flush()
        schedule_info = self.client.parse_schedule()

        if not schedule_info.get("success"):
            logger.warning(f"⚠️ Не вдалося отримати графіки від Рівнеобленерго: {schedule_info.get('error')}")
            sys.stdout.flush()
            return

        current_hash = schedule_info.get("hash")
        days = schedule_info.get("days", [])
        self.cached_days = days
        last_hash = self.state.get("last_hash")
        days_states = self.state.get("days_states", {})

        # Виводимо коротке резюме отриманих даних
        outages_summary = []
        for d in days:
            outage_cnt = sum(
                1 for v in d.get("status_by_subqueue", {}).values()
                if v not in ("Без обмежень", "", "Очікується", "-")
            )
            outages_summary.append(f"{d.get('date')}: обмежень у {outage_cnt} підчергах (Очікується: {d.get('is_pending')})")
        logger.info(f"📊 Дані з сайту отримано ({len(days)} дн.): " + "; ".join(outages_summary))
        sys.stdout.flush()

        # -----------------------------------------------------------------
        # 0. ПЕРЕВІРКА ЕКСТРЕНИХ / АВАРІЙНИХ ВІДКЛЮЧЕНЬ
        # -----------------------------------------------------------------
        is_emergency = schedule_info.get("is_emergency", False)
        was_emergency = self.state.get("is_emergency", False)

        if is_emergency != was_emergency:
            if is_emergency:
                msg_emerg = (
                    "🚨 <b>ВВЕДЕНО ЕКСТРЕНІ / АВАРІЙНІ ВІДКЛЮЧЕННЯ СВІТЛА!</b> 🚨\n\n"
                    "⚠️ За розпорядженням НЕК «Укренерго» у Рівненській області та Сарненському районі "
                    "застосовано аварійні відключення. Графіки погодинних відключень тимчасово не діють!"
                )
                logger.warning("🚨 Введено екстрені відключення світла!")
                if self.send_to_telegram:
                    self.sender._send_text_message(msg_emerg, thread_id=self.thread_id)
            else:
                msg_cancel = (
                    "✅ <b>ЕКСТРЕНІ ВІДКЛЮЧЕННЯ СКАСОВАНО!</b> ✅\n\n"
                    "Повертаємося до прогнозованих графіків погодинних відключень."
                )
                logger.info("✅ Екстрені відключення скасовано.")
                if self.send_to_telegram:
                    self.sender._send_text_message(msg_cancel, thread_id=self.thread_id)

            self.state["is_emergency"] = is_emergency
            self._save_state()

        # -----------------------------------------------------------------
        # 1. ПЕРЕВІРКА ЧАСОВИХ ПОДІЙ (За 10 хвилин до відключення)
        # -----------------------------------------------------------------
        self.check_timeline_events(days)

        # -----------------------------------------------------------------
        # 2. ПЕРЕВІРКА ТА ПУБЛІКАЦІЯ ГРАФІКІВ (при першому запуску, нові дні, оновлення)
        # -----------------------------------------------------------------
        schedule_published = False

        for day in days:
            d_date = day.get("date", "")
            new_sq_status = day.get("status_by_subqueue", {})
            old_sq_status = days_states.get(d_date)
            has_outages = day.get("has_outages", False)

            is_already_sent = d_date in self.sent_schedules
            has_changed = old_sq_status is not None and old_sq_status != new_sq_status

            # Якщо ввімкнено SEND_INITIAL_POWER або перший старт сесії
            should_send_initial = (is_startup or SEND_INITIAL_POWER) and (d_date not in self.startup_sent)

            # Публікуємо графік, тільки якщо є реальні відключення
            if has_outages:
                if not is_already_sent or should_send_initial:
                    prefix_log = "📢 [Перший запуск] " if should_send_initial else "📢 "
                    logger.info(f"{prefix_log}Публікація графіка відключень на {d_date} у Telegram (ветка {self.thread_id})...")
                    msg = self.format_schedule_message(
                        day,
                        title_prefix=f"📈 <b>Графік відключень на {d_date}</b>",
                    )
                    if self.send_to_telegram:
                        sent_ok = self.sender._send_text_message(msg, thread_id=self.thread_id)
                        if sent_ok:
                            logger.info(f"✅ Графік на {d_date} успішно надіслано в Telegram!")
                        else:
                            logger.error(f"❌ Помилка надсилання графіка на {d_date} в Telegram!")
                        time.sleep(2)
                    self.sent_schedules.add(d_date)
                    self.startup_sent.add(d_date)
                    schedule_published = True

                elif has_changed:
                    # Диспетчер оновив години для вже надісланого графіка
                    logger.info(f"🔄 Оновлено години відключень на {d_date}!")
                    msg = self.format_schedule_message(
                        day,
                        title_prefix=f"🔄 <b>Оновлено графік відключень на {d_date}</b>",
                    )
                    if self.send_to_telegram:
                        self.sender._send_text_message(msg, thread_id=self.thread_id)
                        time.sleep(2)
                    schedule_published = True

            days_states[d_date] = new_sq_status

        if current_hash != last_hash or schedule_published:
            self.state["last_hash"] = current_hash
            self.state["days_states"] = days_states
            self.state["initial_sent"] = True
            self._save_state()
            logger.info("💾 Стан графіків оновлено та збережено.")
        else:
            logger.info("⏸ Графіки без змін. Пропускаємо.")
        sys.stdout.flush()

    def run_live(self, poll_interval: Optional[int] = None):
        """Запускає безперервний цикл моніторингу."""
        site_poll_interval = poll_interval or self.poll_interval
        logger.info("⚡️ Запуск моніторингу відключень Рівнеобленерго (Сарни)...")
        logger.info(f"   📍 Цільовий Telegram Thread ID: {self.thread_id}")
        logger.info(f"   ⏱ Інтервал перевірки сайту: кожні {site_poll_interval} сек ({site_poll_interval // 60} хв)")
        logger.info(f"   🔔 Попередження: за {self.warn_minutes} хв до початку відключень (перевірка кожні 30 сек)")
        sys.stdout.flush()

        # 1. Перший старт: обов'язково отримуємо актуальні дані з сайту
        try:
            self.check_and_notify(is_startup=True)
        except Exception as e:
            logger.error(f"❌ Помилка під час початкової перевірки графіків: {e}", exc_info=True)

        last_site_check = time.time()

        # 2. Постійний цикл: кожні 30 сек перевіряємо часову шкалу (за 10 хв до вимкнення),
        #    а сайт опитуємо раз на site_poll_interval (наприклад, щогодини).
        while True:
            try:
                now = time.time()
                if (now - last_site_check) >= site_poll_interval:
                    self.check_and_notify(is_startup=False)
                    last_site_check = now
                else:
                    if self.cached_days:
                        self.check_timeline_events(self.cached_days)
            except Exception as e:
                logger.error(f"❌ Помилка в циклі моніторингу відключень: {e}", exc_info=True)

            time.sleep(30)
