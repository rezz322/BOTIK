import sys
import logging

# Налаштування виводу консолі
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from radar.monitor import SarnyRadarMonitor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("eRadarSarny")


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
