# -*- coding: utf-8 -*-
import sys
import logging

# Налаштування виводу консолі
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from power.monitor import SarnyPowerMonitor
from config import POWER_POLL_INTERVAL, THREAD_ID_POWER, POWER_WARN_MINUTES

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("PowerRunner")


if __name__ == "__main__":
    print("=" * 65, flush=True)
    print("⚡️ МОНІТОРИНГ ВІДКЛЮЧЕНЬ СВІТЛА: САРНИ (РІВНЕОБЛЕНЕРГО)", flush=True)
    print(f"👉 Цільовий Telegram Thread ID: {THREAD_ID_POWER}", flush=True)
    print(f"⏱ Інтервал перевірки сайту: {POWER_POLL_INTERVAL} сек ({POWER_POLL_INTERVAL // 60} хв)", flush=True)
    print(f"🔔 Попередження: за {POWER_WARN_MINUTES} хв до початку відключень", flush=True)
    print("=" * 65, flush=True)
    sys.stdout.flush()

    monitor = SarnyPowerMonitor(send_to_telegram=True, poll_interval=POWER_POLL_INTERVAL)
    monitor.run_live()
