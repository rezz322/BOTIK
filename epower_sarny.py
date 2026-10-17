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
from power.client import RivneoblenergoClient
from config import POWER_POLL_INTERVAL

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("PowerRunner")


if __name__ == "__main__":
    client = RivneoblenergoClient()
    try:
        schedule_data = client.parse_schedule()
    except Exception as e:
        schedule_data = {"success": False, "error": str(e)}

    print("=" * 65)
    print("⚡️ МОНІТОРИНГ ВІДКЛЮЧЕНЬ СВІТЛА: САРНИ (РІВНЕОБЛЕНЕРГО)")
    if schedule_data.get("success"):
        days = schedule_data.get("days", [])
        print(f"👉 Отримано днів у графіку: {len(days)}")
        for d in days:
            outage_cnt = sum(
                1 for v in d["status_by_subqueue"].values()
                if v not in ("Без обмежень", "", "Очікується", "-")
            )
            print(f"   • {d['date']}: обмежень у {outage_cnt} підчергах (Очікується: {d['is_pending']})")
    else:
        print(f"ℹ️ Спроба підключення до Рівнеобленерго: {schedule_data.get('error')}")
    print("=" * 65)

    monitor = SarnyPowerMonitor(send_to_telegram=True, poll_interval=POWER_POLL_INTERVAL)
    monitor.run_live()
