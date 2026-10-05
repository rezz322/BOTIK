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
logger = logging.getLogger("RadarMonitor")


if __name__ == "__main__":
    monitor = SarnyRadarMonitor(send_to_telegram=True)
    data = monitor.get_status()
    print("=" * 65)
    print("📍 МОНІТОРИНГ ЗАГРОЗ ERADAR + КУПОЛ (САРНИ, ОДЕСА ТА КОРЮКІВКА):")
    for r_id, r_cfg in monitor.regions.items():
        is_al = data["alarms_by_region"].get(r_id, False)
        al_txt = "🔴 ТРИВОГА" if is_al else "🟢 ВІДБІЙ"
        d_cnt = len(data["dangers_by_region"].get(r_id, []))
        k_cnt = len(data["kupol_by_region"].get(r_id, []))
        th_id = monitor.get_thread_for_region(r_id)
        print(f"👉 [{r_cfg['name']}] (Thread ID: {th_id})")
        print(f"   Статус: {al_txt} | eRadar цілей: {d_cnt} | КУПОЛ цілей: {k_cnt}")
    print("=" * 65)
    # Запуск постійного моніторингу в реальному часі (кожні 15 сек)
    monitor.run_live(poll_interval=15)
