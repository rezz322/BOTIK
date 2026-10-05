import logging
from radar.utils import (
    SARNY_LAT,
    SARNY_LNG,
    SARNY_RADIUS_KM,
    SARNY_KEYWORDS,
    haversine_km,
    heading_to_compass,
)

logger = logging.getLogger("KupolClient")


class KupolClient:
    """Клієнт сервісу КУПОЛ (kupol.in.ua / NEPTUN OSINT)."""

    def __init__(self, session):
        self.session = session

    def get_threats_for_sarny(self) -> list:
        """
        Отримує активні загрози від КУПОЛ (kupol.in.ua / NEPTUN):
        1. Запитує https://kupol.in.ua/api/threats/active
        2. Фільтрує загрози по координатах до Сарн (радіус SARNY_RADIUS_KM)
           або по ключових словах Сарненщини в описі чи назві регіону.
        3. Розраховує азимут/напрямок руху та дистанцію.
        """
        threats_found = []
        try:
            r = self.session.get("https://kupol.in.ua/api/threats/active", timeout=10)
            if r.status_code == 200:
                threats = r.json().get("threats", [])
                for t in threats:
                    tid = str(t.get("id"))
                    coords = t.get("coordinates")
                    lat, lng = None, None
                    dist = 9999
                    if coords and len(coords) >= 2:
                        # Увага: формат координат у КУПОЛ — [lng, lat]
                        lng = coords[0]
                        lat = coords[1]
                        dist = haversine_km(SARNY_LAT, SARNY_LNG, lat, lng)

                    note = t.get("noteUk") or ""
                    region = t.get("regionNameUk") or ""
                    comb_text = f"{note} {region}".lower()

                    is_sarny_area = (dist <= SARNY_RADIUS_KM) or any(k in comb_text for k in SARNY_KEYWORDS)

                    if is_sarny_area:
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

                        threats_found.append({
                            "id": tid,
                            "threat_type": threat_display,
                            "note": note,
                            "region": region,
                            "heading": heading,
                            "course_desc": course_desc,
                            "distance_km": round(dist, 1) if dist < 9999 else None,
                            "lat": lat,
                            "lng": lng,
                            "source_label": t.get("sourceLabel") or "NEPTUN",
                        })
        except Exception as e:
            logger.error(f"Помилка отримання даних з КУПОЛ (kupol.in.ua): {e}")

        return threats_found

    def check_sarny_alarm(self) -> bool | None:
        """Перевіряє районний статус тривоги Сарненського району з КУПОЛ."""
        try:
            r = self.session.get("https://kupol.in.ua/api/alerts/active", timeout=10)
            if r.status_code == 200:
                alerts = r.json().get("alerts", [])
                for a in alerts:
                    reg_id = str(a.get("regionId") or "").lower()
                    reg_name = str(a.get("regionNameUk") or "").lower()
                    if "сарненськ" in reg_id or "сарненськ" in reg_name:
                        return a.get("status") == "active"
                return False
        except Exception as e:
            logger.error(f"Помилка отримання районного статусу з КУПОЛ: {e}")
        return None
