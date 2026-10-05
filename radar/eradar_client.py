import logging
from radar.utils import (
    MONITORED_REGIONS,
    THREAT_TRANSLATION,
    haversine_km,
    filter_relevant_lines_for_region,
)

logger = logging.getLogger("ERadarClient")


class ERadarClient:
    """Клієнт сервісу eRadar (eradar.app)."""

    def __init__(self, session):
        self.session = session

    def get_dangers_for_regions(self, regions: dict = None) -> tuple[dict[str, list], set, set]:
        """
        Отримує активні загрози з eRadar та розподіляє їх по регіонах (Сарни, Одеса тощо).
        Виконує лише 1 запит до API eRadar.
        Повертає: (словник {region_id: [цілі]}, множину last_message_id, множину message_keys).
        """
        if regions is None:
            regions = MONITORED_REGIONS

        dangers_by_region = {r_id: [] for r_id in regions}
        danger_feed_ids = set()
        danger_message_keys = set()

        try:
            r = self.session.get("https://eradar.app/api/dangers", impersonate="chrome124", timeout=15)
            if r.status_code == 200:
                dangers = r.json().get("dangers", [])
                for d in dangers:
                    name = (d.get("canonical_name") or "").lower()
                    lat = d.get("lat")
                    lng = d.get("lng")
                    threat_raw = d.get("threat_type", "unknown")
                    threat_title = THREAT_TRANSLATION.get(threat_raw, threat_raw)
                    raw_excerpt = d.get("message_excerpt") or ""

                    last_msg_id = d.get("last_message_id")
                    tg_msg_id = d.get("tg_message_id")
                    ch = d.get("channel")

                    if last_msg_id:
                        danger_feed_ids.add(str(last_msg_id))
                    if ch and tg_msg_id:
                        danger_message_keys.add(f"{ch}_{tg_msg_id}")

                    for r_id, r_cfg in regions.items():
                        dist = haversine_km(r_cfg["lat"], r_cfg["lng"], lat, lng) if (lat and lng) else 9999
                        is_target_area = any(k in name for k in r_cfg.get("keywords", [])) or (dist <= r_cfg["radius_km"])

                        if is_target_area:
                            filtered_excerpt = filter_relevant_lines_for_region(raw_excerpt, r_cfg)

                            dangers_by_region[r_id].append({
                                "id": f"{d.get('id')}_{r_id}",
                                "raw_id": d.get("id"),
                                "region_id": r_id,
                                "region_name": r_cfg["name"],
                                "threat_type": threat_title,
                                "place": d.get("canonical_name"),
                                "distance_km": round(dist, 1) if dist < 9999 else None,
                                "channel": ch,
                                "text": filtered_excerpt or raw_excerpt,
                                "raw_text": raw_excerpt,
                                "expires_at": d.get("expires_at"),
                                "last_message_id": last_msg_id,
                                "tg_message_id": tg_msg_id,
                            })
        except Exception as e:
            logger.error(f"Помилка отримання dangers з eRadar: {e}")

        return dangers_by_region, danger_feed_ids, danger_message_keys

    def get_feed_for_regions(
        self,
        danger_feed_ids: set,
        danger_message_keys: set,
        regions: dict = None,
    ) -> dict[str, list]:
        """
        Отримує стрічку моніторингу eRadar та фільтрує її для кожного регіону (Сарни, Одеса тощо).
        Виконує лише 1 запит до API.
        """
        if regions is None:
            regions = MONITORED_REGIONS

        feed_by_region = {r_id: [] for r_id in regions}

        try:
            r = self.session.get("https://eradar.app/api/feed?limit=50", impersonate="chrome124", timeout=15)
            if r.status_code == 200:
                feed = r.json().get("feed", [])
                for item in feed:
                    fid = str(item.get("id"))
                    ch = item.get("channel")
                    tg_id = item.get("tg_message_id")
                    msg_key = f"{ch}_{tg_id}" if ch and tg_id else None

                    # Фільтруємо автоматичні ботові канали сигналів (UkraineAlarmSignal),
                    # які створюють спам типу "Жовтий рівень", "Відбій по району" тощо.
                    if ch == "UkraineAlarmSignal":
                        continue

                    # Якщо це повідомлення вже виявлено як активна ціль (Danger), не дублюємо у Feed!
                    if fid in danger_feed_ids or (msg_key and msg_key in danger_message_keys):
                        continue

                    raw_text = item.get("text") or ""

                    for r_id, r_cfg in regions.items():
                        filtered_text = filter_relevant_lines_for_region(raw_text, r_cfg)
                        if filtered_text:
                            item_copy = dict(item)
                            item_copy["filtered_text"] = filtered_text
                            item_copy["region_id"] = r_id
                            item_copy["region_name"] = r_cfg["name"]
                            feed_by_region[r_id].append(item_copy)
        except Exception as e:
            logger.error(f"Помилка отримання feed з eRadar: {e}")

        return feed_by_region

    def get_dangers_for_sarny(self) -> tuple[list, set, set]:
        """Сумісність зі старим кодом."""
        by_reg, d_ids, d_keys = self.get_dangers_for_regions(MONITORED_REGIONS)
        return by_reg.get("sarny", []), d_ids, d_keys

    def get_feed_for_sarny(self, danger_feed_ids: set, danger_message_keys: set) -> list:
        """Сумісність зі старим кодом."""
        by_reg = self.get_feed_for_regions(danger_feed_ids, danger_message_keys, MONITORED_REGIONS)
        return by_reg.get("sarny", [])

    def check_alarm_signal_for_region(self, region_cfg: dict) -> bool | None:
        """Перевірка стрічки офіційних сигналів @UkraineAlarmSignal у eRadar для конкретного регіону."""
        try:
            r = self.session.get("https://eradar.app/api/feed?limit=50", impersonate="chrome124", timeout=10)
            if r.status_code == 200:
                feed = r.json().get("feed", [])
                raion_keywords = region_cfg.get("raion_keywords", [])
                for item in feed:
                    if item.get("channel") == "UkraineAlarmSignal":
                        txt = (item.get("text") or "").lower()
                        if any(k in txt for k in raion_keywords):
                            if "🟢" in txt or "відбій" in txt:
                                return False
                            if "🔴" in txt or "🟡" in txt or "тривог" in txt:
                                return True
        except Exception as e:
            logger.error(f"Помилка отримання стрічки UkraineAlarmSignal для {region_cfg['name']}: {e}")
        return None

    def check_alarm_signal_feed(self) -> bool | None:
        """Сумісність зі старим кодом."""
        return self.check_alarm_signal_for_region(MONITORED_REGIONS["sarny"])
