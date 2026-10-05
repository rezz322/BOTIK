# -*- coding: utf-8 -*-
import logging
from radar.utils import (
    MONITORED_REGIONS,
    SARNY_LAT,
    SARNY_LNG,
    haversine_km,
    heading_to_compass,
    extract_kupol_location,
    clean_text_line,
)

logger = logging.getLogger("KupolClient")


class KupolClient:
    """Клієнт сервісу КУПОЛ (kupol.in.ua / NEPTUN OSINT)."""

    def __init__(self, session):
        self.session = session

    def check_alarm_for_region(self, region_cfg: dict) -> bool | None:
        """
        Перевіряє районний або обласний статус тривоги для обраного регіону (Сарни тощо) з КУПОЛ.
        Повертає:
          True  - тривога активна (районна або по всій області)
          False - тривоги немає (ВІДБІЙ)
          None  - помилка мережі
        """
        try:
            r = self.session.get("https://kupol.in.ua/api/alerts/active", impersonate="chrome124", timeout=10)
            if r.status_code == 200:
                alerts = r.json().get("alerts", [])
                target_raion_id = str(region_cfg.get("kupol_raion_id", "")).lower()
                raion_keywords = [k.lower() for k in region_cfg.get("raion_keywords", [])]
                oblast_keywords = [k.lower() for k in region_cfg.get("oblast_keywords", [])]

                for a in alerts:
                    if a.get("status") != "active":
                        continue

                    level = str(a.get("level") or "").lower()
                    reg_id = str(a.get("regionId") or "").lower()
                    reg_name = str(a.get("regionNameUk") or "").lower()
                    oblast_name = str(a.get("oblastNameUk") or "").lower()

                    # 1. Прямий збіг по конкретному району
                    if target_raion_id and target_raion_id in reg_id:
                        return True
                    if any(k in reg_name or k in reg_id for k in raion_keywords):
                        return True

                    # 2. Збіг по всій області (якщо тривога оголошена на обласному рівні)
                    if level == "oblast":
                        if any(k in reg_name or k in reg_id for k in oblast_keywords):
                            return True
                    elif oblast_name and any(k in oblast_name for k in oblast_keywords):
                        # Районна тривога в межах нашої області
                        if any(k in reg_name for k in raion_keywords):
                            return True

                return False
        except Exception as e:
            logger.error(f"Помилка отримання статусу тривоги з КУПОЛ для {region_cfg.get('name', 'регіону')}: {e}")
        return None

    def check_sarny_alarm(self) -> bool | None:
        """Сумісність зі старим кодом."""
        return self.check_alarm_for_region(MONITORED_REGIONS["sarny"])

    def get_threats(self, mode: str = "all_ukraine", regions: dict = None) -> list:
        """
        Отримує активні загрози від КУПОЛ (kupol.in.ua / NEPTUN).
        Параметри:
          mode = "all_ukraine" - повертає всі виявлені повітряні цілі по Україні
          mode = "sarny"       - фільтрує цілі тільки в радіусі Сарн (<= 60 км) або за ключовими словами
        """
        if regions is None:
            regions = MONITORED_REGIONS

        sarny_cfg = regions.get("sarny", MONITORED_REGIONS["sarny"])
        threats_list = []

        try:
            r = self.session.get("https://kupol.in.ua/api/threats/active", impersonate="chrome124", timeout=10)
            if r.status_code == 200:
                threats = r.json().get("threats", [])
                for t in threats:
                    tid = str(t.get("id"))
                    coords = t.get("coordinates")
                    lat, lng = None, None
                    if coords and len(coords) >= 2:
                        lng = float(coords[0])
                        lat = float(coords[1])

                    note = t.get("noteUk") or ""
                    region_name = t.get("regionNameUk") or ""
                    comb_text = f"{note} {region_name}".lower()

                    heading = t.get("headingDeg")
                    course_desc = heading_to_compass(heading) if heading is not None else None
                    speed_kmh = t.get("speedKmh")
                    source_count = t.get("sourceCount") or 1

                    raw_kind = (t.get("kind") or "").lower()
                    raw_label = t.get("labelUk") or raw_kind

                    if "fpv" in raw_kind or "fpv" in raw_label.lower():
                        threat_icon = "🛸"
                    elif "uav" in raw_kind or "дрон" in raw_label.lower() or "бпла" in raw_label.lower():
                        threat_icon = "🛵"
                    elif "missile" in raw_kind or "ракет" in raw_label.lower() or "баліст" in raw_label.lower():
                        threat_icon = "🚀"
                    elif "kab" in raw_kind or "каб" in raw_label.lower():
                        threat_icon = "💣"
                    elif "aviation" in raw_kind or "авіа" in raw_label.lower():
                        threat_icon = "✈️"
                    else:
                        threat_icon = "🎯"

                    threat_display = f"{threat_icon} {raw_label}"

                    # Розрахунок відстані до Сарн
                    dist_sarny = haversine_km(SARNY_LAT, SARNY_LNG, lat, lng) if (lat and lng) else None
                    is_near_sarny = (dist_sarny is not None and dist_sarny <= sarny_cfg["radius_km"]) or any(
                        k in comb_text for k in sarny_cfg.get("keywords", [])
                    )

                    # Визначаємо людиночитабельну локацію
                    loc_name = extract_kupol_location(note, region_name)

                    threat_obj = {
                        "id": f"{tid}_kupol",
                        "raw_id": tid,
                        "threat_type": threat_display,
                        "kind": raw_kind,
                        "label": raw_label,
                        "note": note,
                        "region": region_name,
                        "location": loc_name,
                        "heading": heading,
                        "course_desc": course_desc,
                        "speed_kmh": speed_kmh,
                        "confirmations": source_count,
                        "distance_km": round(dist_sarny, 1) if dist_sarny is not None else None,
                        "is_near_sarny": is_near_sarny,
                        "lat": lat,
                        "lng": lng,
                        "source_label": t.get("sourceLabel") or "NEPTUN",
                        "expires_at": t.get("expiresAt"),
                    }

                    if mode == "all_ukraine":
                        threats_list.append(threat_obj)
                    elif mode == "sarny":
                        if is_near_sarny:
                            threats_list.append(threat_obj)
                    else:
                        # За замовчуванням якщо невідомий режим
                        threats_list.append(threat_obj)

        except Exception as e:
            logger.error(f"Помилка отримання даних з КУПОЛ (kupol.in.ua): {e}")

        return threats_list

    def get_threats_for_regions(self, regions: dict = None, mode: str = "all_ukraine") -> dict[str, list]:
        """
        Розподіляє загрози КУПОЛ по регіонах для зворотної сумісності з монітором.
        Якщо mode == 'all_ukraine', прив'язує знайдені загрози до першого доступного регіону (Сарни),
        щоб вони гарантовано були надіслані у відповідну гілку сповіщень.
        """
        if regions is None:
            regions = MONITORED_REGIONS

        all_threats = self.get_threats(mode=mode, regions=regions)
        results = {r_id: [] for r_id in regions}

        if mode == "all_ukraine":
            # У режимі всієї України всі загрози направляються в активний канал сповіщень (Сарни / THREAD_ID_ALERTS)
            first_reg = list(regions.keys())[0] if regions else "sarny"
            results[first_reg] = all_threats
        else:
            # У режимі Сарн фільтруємо тільки для Сарн
            for th in all_threats:
                if th.get("is_near_sarny") and "sarny" in results:
                    results["sarny"].append(th)

        return results

    def get_threats_for_sarny(self) -> list:
        """Сумісність зі старим кодом."""
        return self.get_threats(mode="sarny")
