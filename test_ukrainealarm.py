# -*- coding: utf-8 -*-
import sys
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from radar.ukrainealarm_client import UkraineAlarmClient
from radar.utils import SARNY_COMMUNITIES, SARNY_RADIUS_KM


def main():
    print("=" * 65)
    print("🧪 ТЕСТУВАННЯ БЕЗКОШТОВНОГО API MAP.UKRAINEALARM.COM ДЛЯ САРН")
    print("=" * 65)

    client = UkraineAlarmClient()
    print("⏳ Отримання даних з map.ukrainealarm.com...")
    data = client.get_status_for_sarny(radar_radius_km=SARNY_RADIUS_KM)

    overall_alarm = data["overall_alarm"]
    alarm_status = "🔴 ТРИВОГА" if overall_alarm else "🟢 ВІДБІЙ (тривоги немає)"

    print(f"\n📍 Загальний статус Сарненського району: {alarm_status}")
    print(f"   Обласна тривога (Рівненська область, ID 5): {'ТАК' if data['is_oblast_alarm'] else 'НІ'}")
    print(f"   Районна тривога (Сарненський район, ID 113): {'ТАК' if data['is_district_alarm'] else 'НІ'}")
    print(f"   Громад під прямою тривогою: {len(data['active_communities'])} із {len(SARNY_COMMUNITIES)}")
    if data["reasons"]:
        print(f"   Причини тривоги: {', '.join(data['reasons'])}")

    print("\n🏘 ПЕРЕВІРКА ПІДРАЙОНІВ ТА ТЕРИТОРІАЛЬНИХ ГРОМАД САРНЕНСЬКОГО РАЙОНУ:")
    for comm_id, comm in SARNY_COMMUNITIES.items():
        is_comm_alarm = comm_id in data["active_communities"] or data["is_district_alarm"] or data["is_oblast_alarm"]
        comm_status_icon = "🔴 ТРИВОГА" if is_comm_alarm else "🟢 Відбій"
        print(f"  - [{comm_status_icon}] {comm['name']} (центр: {comm['short_name']}, {comm['lat']}, {comm['lng']})")

    print(f"\n🎯 РАДАР: ЦІЛЕЙ ПОБЛИЗУ РАЙОНУ (радіус <= {SARNY_RADIUS_KM} км): {len(data['targets_near_district'])}")
    for t in data["targets_near_district"]:
        print(f"  ⚠️ {t['type']} -> ~{t['dist_to_sarny_km']} км до Сарн (найближче до: {t['closest_community_short']} ~{t['dist_to_closest_comm_km']} км)")
        print(f"     Джерело: {t['sources_text']}")

    print(f"\n📡 ВСЬОГО ЦІЛЕЙ НА КАРТІ УКРАЇНИ: {len(data['targets'])}")
    if data["targets"]:
        closest = data["targets"][0]
        print(f"  Найближча ціль до Сарн: {closest['type']} на відстані ~{closest['dist_to_sarny_km']} км (біля {closest['closest_community_short']})")

    print(f"\n✈️ ЗЛІТ МіГ-31К: {'АКТИВНИЙ' if data['mig_alerts'] else 'Немає'}")
    print(f"💥 АРТИЛЕРІЯ: {'АКТИВНА' if data['artillery'] else 'Немає'}")
    print("=" * 65)
    print("✅ Тест успішно завершено! API функціонує коректно.")


if __name__ == "__main__":
    main()
