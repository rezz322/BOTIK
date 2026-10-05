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

from radar.monitor import SarnyRadarMonitor

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("RadarMonitor")


if __name__ == "__main__":
    monitor = SarnyRadarMonitor(send_to_telegram=True)
    data = monitor.get_status()
    mode_text = "ВСЯ УКРАЇНА" if monitor.kupol_mode == "all_ukraine" else "ТІЛЬКИ САРНИ"
    print("=" * 65)
    print("📍 МОНІТОРИНГ ЗАГРОЗ ERADAR + КУПОЛ:")
    print(f"⚙️  Режим роботи КУПОЛ: [{mode_text}] (зміна у .env: KUPOL_MODE=all_ukraine або sarny)")
    for r_id, r_cfg in monitor.regions.items():
        is_al = data["alarms_by_region"].get(r_id, False)
        al_txt = "🔴 ТРИВОГА" if is_al else "🟢 ВІДБІЙ"
        d_cnt = len(data["dangers_by_region"].get(r_id, []))
        k_cnt = len(data.get("kupol_threats", []))
        th_id = monitor.get_thread_for_region(r_id)
        print(f"👉 Регіон: [{r_cfg['name']}] (Thread ID: {th_id})")
        print(f"   Статус тривоги: {al_txt}")
        print(f"   eRadar цілей (район): {d_cnt} | КУПОЛ цілей ({mode_text}): {k_cnt}")
    print("=" * 65)
    # Запуск постійного моніторингу в реальному часі (кожні 15 сек)
    monitor.run_live(poll_interval=15)
