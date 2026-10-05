import logging
from radar.utils import (
    MONITORED_REGIONS,
    haversine_km,
    heading_to_compass,
)

logger = logging.getLogger("KupolClient")


class KupolClient:
    """Клієнт сервісу КУПОЛ (kupol.in.ua / NEPTUN OSINT)."""

    def __init__(self, session):
        self.session = session

    def get_threats_for_regions(self, regions: dict = None) -> dict[str, list]:
        """
        Отримує активні загрози від КУПОЛ та розподіляє їх по регіонах (Сарни, Одеса тощо).
        Виконує лише 1 запит до API КУПОЛа.
        """
        if regions is None:
            regions = MONITORED_REGIONS

        results = {r_id: [] for r_id in regions}

        try:
            r = self.session.get("https://kupol.in.ua/api/threats/active", timeout=10)
            if r.status_code == 200:
                threats = r.json().get("threats", [])
                for t in threats:
                    tid = str(t.get("id"))
                    coords = t.get("coordinates")
                    lat, lng = None, None
                    if coords and len(coords) >= 2:
                        lng = coords[0]
                        lat = coords[1]

                    note = t.get("noteUk") or ""
                    region_name = t.get("regionNameUk") or ""
                    comb_text = f"{note} {region_name}".lower()

                    heading = t.get("headingDeg")
                    course_desc = heading_to_compass(heading) if heading is not None else None

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

                    for r_id, r_cfg in regions.items():
                        dist = haversine_km(r_cfg["lat"], r_cfg["lng"], lat, lng) if (lat and lng) else 9999
                        is_target_area = (dist <= r_cfg["radius_km"]) or any(k in comb_text for k in r_cfg.get("keywords", []))

                        if is_target_area:
                            # Строгий фільтр КУПОЛ: пропускаємо якщо загроза не безпосередньо на район
                            strict_keys = r_cfg.get("kupol_strict_keywords", [])
                            strict_radius = r_cfg.get("kupol_strict_radius_km", r_cfg["radius_km"])
                            if strict_keys or strict_radius < r_cfg["radius_km"]:
                                is_strict = (dist <= strict_radius) or any(k in comb_text for k in strict_keys)
                                if not is_strict:
                                    logger.debug(
                                        f"[КУПОЛ] Пропускаємо загрозу {tid} для {r_cfg['short_name']}: "
                                        f"не відповідає строгому фільтру (dist={round(dist,1)} км, text='{comb_text[:60]}')"
                                    )
                                    continue
                            results[r_id].append({
                                "id": f"{tid}_{r_id}",
                                "raw_id": tid,
                                "region_id": r_id,
                                "region_name": r_cfg["name"],
                                "threat_type": threat_display,
                                "note": note,
                                "region": region_name,
                                "heading": heading,
                                "course_desc": course_desc,
                                "distance_km": round(dist, 1) if dist < 9999 else None,
                                "lat": lat,
                                "lng": lng,
                                "source_label": t.get("sourceLabel") or "NEPTUN",
                            })
        except Exception as e:
            logger.error(f"Помилка отримання даних з КУПОЛ (kupol.in.ua): {e}")

        return results

    def get_threats_for_sarny(self) -> list:
        """Сумісність зі старим кодом."""
        res = self.get_threats_for_regions(MONITORED_REGIONS)
        return res.get("sarny", [])

    def check_alarm_for_region(self, region_cfg: dict) -> bool | None:
        """Перевіряє районний статус тривоги для обраного регіону (Сарни або Одеса) з КУПОЛ."""
        try:
            r = self.session.get("https://kupol.in.ua/api/alerts/active", timeout=10)
            if r.status_code == 200:
                alerts = r.json().get("alerts", [])
                target_raion_id = region_cfg.get("kupol_raion_id", "").lower()
                raion_keywords = region_cfg.get("raion_keywords", [])

                for a in alerts:
                    reg_id = str(a.get("regionId") or "").lower()
                    reg_name = str(a.get("regionNameUk") or "").lower()
                    
                    matched = False
                    if target_raion_id and target_raion_id in reg_id:
                        matched = True
                    elif any(k in reg_name or k in reg_id for k in raion_keywords):
                        matched = True

                    if matched:
                        return a.get("status") == "active"
                return False
        except Exception as e:
            logger.error(f"Помилка отримання районного статусу з КУПОЛ для {region_cfg['name']}: {e}")
        return None

    def check_sarny_alarm(self) -> bool | None:
        """Сумісність зі старим кодом."""
        return self.check_alarm_for_region(MONITORED_REGIONS["sarny"])
