# -*- coding: utf-8 -*-
import logging
import time
import re
from datetime import datetime, timezone
from curl_cffi import requests

from radar.utils import (
    SARNY_LAT,
    SARNY_LNG,
    SARNY_DISTRICT_ID,
    RIVNE_STATE_ID,
    SARNY_COMMUNITIES,
    SARNY_RADIUS_KM,
    haversine_km,
    heading_to_compass,
    THREAT_TRANSLATION,
)

logger = logging.getLogger("UkraineAlarmClient")


class UkraineAlarmClient:
    """
    Клієнт до офіційного безкоштовного API системи map.ukrainealarm.com.
    Відстежує:
      - Повітряні тривоги (Рівненська область, Сарненський район та всі 11 територіальних громад)
      - Радарні цілі (БпЛА / ракети) із координатами, вектором і джерелами
      - Загрози МіГ-31К та артилерійських обстрілів
    """

    def __init__(self, session=None):
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36",
            "Accept": "application/json",
        })
        self.base_url = "https://map.ukrainealarm.com"
        self.api_token = None
        self.token_time = 0

    def refresh_token_if_needed(self) -> str | None:
        """Отримує актуальний api-token безпосередньо з веб-інтерфейсу map.ukrainealarm.com."""
        now = time.time()
        # Токен дійсний щонайменше 30 хвилин
        if self.api_token and (now - self.token_time) < 1800:
            return self.api_token

        try:
            r = self.session.get(self.base_url, impersonate="chrome124", timeout=12)
            if r.status_code == 200:
                match = re.search(r'<input id="api-token"[^>]*value="([^"]+)"', r.text)
                if match:
                    self.api_token = match.group(1)
                    self.token_time = now
                    logger.debug("Оновлено токен доступу map.ukrainealarm.com")
                    return self.api_token
        except Exception as e:
            logger.warning(f"Не вдалося отримати токен з map.ukrainealarm.com: {e}")

        return self.api_token

    def fetch_map_update(self) -> dict | None:
        """
        Отримує повний набір даних моніторингу:
        /api/v2/data/mapUpdate (тривоги, цілі, МіГ, артилерія).
        """
        token = self.refresh_token_if_needed()
        headers = {
            "Referer": f"{self.base_url}/",
            "Accept": "application/json",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"

        url = f"{self.base_url}/api/v2/data/mapUpdate"
        try:
            r = self.session.get(url, headers=headers, impersonate="chrome124", timeout=10)
            if r.status_code == 200:
                return r.json()
            elif r.status_code == 401:
                # Токен застарів — примусово оновлюємо
                self.api_token = None
                new_token = self.refresh_token_if_needed()
                if new_token:
                    headers["Authorization"] = f"Bearer {new_token}"
                    r = self.session.get(url, headers=headers, impersonate="chrome124", timeout=10)
                    if r.status_code == 200:
                        return r.json()
            logger.warning(f"Неочікувана відповідь від mapUpdate: HTTP {r.status_code}")
        except Exception as e:
            logger.error(f"Помилка запиту до mapUpdate: {e}")

        # Резервний запит: getAlerts
        try:
            url_backup = f"{self.base_url}/api/data/getAlerts"
            r_b = self.session.get(url_backup, headers=headers, impersonate="chrome124", timeout=10)
            if r_b.status_code == 200:
                return {"alerts": r_b.json(), "locations": {}, "migAlerts": [], "artillery": []}
        except Exception as e:
            logger.error(f"Помилка резервного запиту до getAlerts: {e}")

        return None

    def get_target_unique_id(self, target: dict) -> str:
        """Створює унікальний ключ для цілі на карті для уникнення дублікатів."""
        t_type = target.get("type", "target")
        sources = target.get("sources", [])
        if sources:
            src = sources[0]
            nick = src.get("ChatNickname") or src.get("ChatName") or "src"
            msg_id = src.get("MessageId") or src.get("MessageTime") or ""
            return f"{t_type}_{nick}_{msg_id}"

        lat = round(float(target.get("lat", 0)), 2)
        lon = round(float(target.get("lon", 0)), 2)
        return f"{t_type}_{lat}_{lon}"

    def get_status_for_sarny(self, map_data: dict = None, radar_radius_km: float = SARNY_RADIUS_KM) -> dict:
        """
        Повний аналіз загроз та статусу тривоги для Сарненського району
        та всіх його 11 підрайонів (громад).
        """
        if map_data is None:
            map_data = self.fetch_map_update() or {}

        alerts = map_data.get("alerts", [])
        mig_alerts = map_data.get("migAlerts", [])
        artillery = map_data.get("artillery", [])
        locations = map_data.get("locations", {})
        raw_targets = locations.get("targets", []) if isinstance(locations, dict) else []

        is_rivne_oblast_alarm = False
        is_sarny_raion_alarm = False
        active_communities = {}
        all_reasons = []
        all_levels = []

        for al in alerts:
            rid = str(al.get("regionId", ""))
            rtype = str(al.get("regionType", ""))
            rname = str(al.get("regionName", "")).lower()
            reng = str(al.get("regionEngName", "")).lower()

            reasons_for_item = []
            levels_for_item = []
            for act in al.get("activeAlerts", []):
                for lvl in act.get("activeAlertLevels", []):
                    reason_txt = lvl.get("reason", "").strip()
                    lvl_name = lvl.get("alertLevel", "").strip()
                    if reason_txt:
                        reasons_for_item.append(reason_txt)
                    if lvl_name:
                        levels_for_item.append(lvl_name)

            # Перевірка виключно на рівні Сарненського району (Сарненський район, ID 113)
            # Рівненську область (ID 5) та м. Рівне повністю ігноруємо
            if rid == SARNY_DISTRICT_ID or (rtype == "District" and ("сарненськ" in rname or "sarn" in reng)):
                is_sarny_raion_alarm = True
                if reasons_for_item:
                    all_reasons.extend(reasons_for_item)
                if levels_for_item:
                    all_levels.extend(levels_for_item)

        # Загальний статус тривоги: виключно Сарненський район
        overall_alarm = is_sarny_raion_alarm

        unique_reasons = list(dict.fromkeys(all_reasons))
        unique_levels = list(dict.fromkeys(all_levels))

        # Обробка радарних цілей поблизу Сарн та громад
        sarny_targets = []
        for t in raw_targets:
            lat = t.get("lat")
            lon = t.get("lon")
            if lat is None or lon is None:
                continue

            dist_to_sarny = haversine_km(SARNY_LAT, SARNY_LNG, lat, lon)

            # Знаходимо найближчу громаду Сарненського району
            closest_comm = None
            min_comm_dist = 999999.0
            for comm_id, comm_cfg in SARNY_COMMUNITIES.items():
                cdist = haversine_km(comm_cfg["lat"], comm_cfg["lng"], lat, lon)
                if cdist < min_comm_dist:
                    min_comm_dist = cdist
                    closest_comm = comm_cfg

            t_type = str(t.get("type", "Unknown")).lower()
            threat_name = THREAT_TRANSLATION.get(t_type, f"⚠️ {t.get('type')}")

            sources_list = []
            for s in t.get("sources", []):
                s_name = s.get("ChatName") or s.get("ChatNickname") or "Повітряні Сили ЗСУ"
                sources_list.append(s_name)

            sources_text = ", ".join(dict.fromkeys(sources_list)) if sources_list else "map.ukrainealarm.com"
            unique_id = self.get_target_unique_id(t)
            rot = t.get("rotation")
            compass = heading_to_compass(rot) if rot is not None else ""

            is_near_district = (min_comm_dist <= radar_radius_km) or (dist_to_sarny <= radar_radius_km)

            sarny_targets.append({
                "id": unique_id,
                "type": threat_name,
                "raw_type": t.get("type"),
                "lat": lat,
                "lon": lon,
                "rotation": rot,
                "compass": compass,
                "dist_to_sarny_km": round(dist_to_sarny, 1),
                "closest_community_name": closest_comm["name"] if closest_comm else "Сарненська громада",
                "closest_community_short": closest_comm["short_name"] if closest_comm else "Сарни",
                "dist_to_closest_comm_km": round(min_comm_dist, 1),
                "is_near_district": is_near_district,
                "sources_text": sources_text,
                "raw": t,
            })

        # Сортуємо цілі за близькістю до району
        sarny_targets.sort(key=lambda x: x["dist_to_closest_comm_km"])

        return {
            "overall_alarm": overall_alarm,
            "is_oblast_alarm": is_rivne_oblast_alarm,
            "is_district_alarm": is_sarny_raion_alarm,
            "active_communities": active_communities,
            "reasons": unique_reasons,
            "alert_levels": unique_levels,
            "mig_alerts": mig_alerts,
            "artillery": artillery,
            "targets": sarny_targets,
            "targets_near_district": [t for t in sarny_targets if t["is_near_district"]],
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
