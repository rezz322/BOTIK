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
from radar.utils import SARNY_COMMUNITIES
from config import ALERTS_POLL_INTERVAL, RADAR_RADIUS_KM

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("RadarMonitor")


if __name__ == "__main__":
    monitor = SarnyRadarMonitor(send_to_telegram=True, radar_radius_km=RADAR_RADIUS_KM)
    data = monitor.get_status()

    is_alarm = data["overall_alarm"]
    alarm_txt = "🔴 ТРИВОГА" if is_alarm else "🟢 ВІДБІЙ"

    print("=" * 65)
    print("📍 МОНІТОРИНГ ТРИВОГ ТА РАДАРУ: MAP.UKRAINEALARM.COM")
    print(f"👉 Сарненський район: {alarm_txt}")
    print(f"   Область: {'ТАК' if data['is_oblast_alarm'] else 'НІ'} | Район: {'ТАК' if data['is_district_alarm'] else 'НІ'}")
    print(f"   Громад під тривогою: {len(data['active_communities'])} із {len(SARNY_COMMUNITIES)}")
    print(f"   Цілей поблизу району (<={RADAR_RADIUS_KM} км): {len(data['targets_near_district'])}")
    print(f"   Всього цілей на карті України: {len(data['targets'])}")
    print("=" * 65)

    # Запуск постійного моніторингу в реальному часі
    monitor.run_live(poll_interval=ALERTS_POLL_INTERVAL)
