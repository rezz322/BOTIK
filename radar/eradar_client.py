import logging
from radar.utils import (
    SARNY_LAT,
    SARNY_LNG,
    SARNY_RADIUS_KM,
    SARNY_KEYWORDS,
    THREAT_TRANSLATION,
    haversine_km,
    filter_relevant_lines,
)

logger = logging.getLogger("ERadarClient")


class ERadarClient:
    """Клієнт сервісу eRadar (eradar.app)."""

    def __init__(self, session):
        self.session = session

    def get_dangers_for_sarny(self) -> tuple[list, set, set]:
        """
        Отримує активні загрози з eRadar, що загрожують Сарненському району.
        Повертає: (список цілей, множину last_message_id, множину message_keys).
        """
        dangers_found = []
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
                    dist = haversine_km(SARNY_LAT, SARNY_LNG, lat, lng) if (lat and lng) else 9999

                    is_sarny_area = any(k in name for k in SARNY_KEYWORDS) or (dist <= SARNY_RADIUS_KM)
                    if is_sarny_area:
                        threat_raw = d.get("threat_type", "unknown")
                        threat_title = THREAT_TRANSLATION.get(threat_raw, threat_raw)
                        raw_excerpt = d.get("message_excerpt") or ""
                        filtered_excerpt = filter_relevant_lines(raw_excerpt)

                        last_msg_id = d.get("last_message_id")
                        tg_msg_id = d.get("tg_message_id")
                        ch = d.get("channel")

                        if last_msg_id:
                            danger_feed_ids.add(str(last_msg_id))
                        if ch and tg_msg_id:
                            danger_message_keys.add(f"{ch}_{tg_msg_id}")

                        dangers_found.append({
                            "id": d.get("id"),
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

        return dangers_found, danger_feed_ids, danger_message_keys

    def get_feed_for_sarny(self, danger_feed_ids: set, danger_message_keys: set) -> list:
        """
        Отримує стрічку моніторингу eRadar (напрямки, сектори) для Сарненського району.
        """
        feed_found = []
        try:
            r = self.session.get("https://eradar.app/api/feed?limit=50", impersonate="chrome124", timeout=15)
            if r.status_code == 200:
                feed = r.json().get("feed", [])
                for item in feed:
                    fid = str(item.get("id"))
                    ch = item.get("channel")
                    tg_id = item.get("tg_message_id")
                    msg_key = f"{ch}_{tg_id}" if ch and tg_id else None

                    # Якщо це повідомлення вже виявлено як активна ціль (Danger), не дублюємо його у Feed!
                    if fid in danger_feed_ids or (msg_key and msg_key in danger_message_keys):
                        continue

                    raw_text = item.get("text") or ""
                    filtered_text = filter_relevant_lines(raw_text)
                    if not filtered_text:
                        continue

                    item["filtered_text"] = filtered_text
                    feed_found.append(item)
        except Exception as e:
            logger.error(f"Помилка отримання feed з eRadar: {e}")

        return feed_found

    def check_alarm_signal_feed(self) -> bool | None:
        """Перевірка стрічки офіційних сигналів @UkraineAlarmSignal у eRadar."""
        try:
            r = self.session.get("https://eradar.app/api/feed?limit=50", impersonate="chrome124", timeout=10)
            if r.status_code == 200:
                feed = r.json().get("feed", [])
                for item in feed:
                    if item.get("channel") == "UkraineAlarmSignal":
                        txt = (item.get("text") or "").lower()
                        if "сарненськ" in txt:
                            if "🟢" in txt or "відбій" in txt:
                                return False
                            if "🔴" in txt or "🟡" in txt or "тривог" in txt:
                                return True
        except Exception as e:
            logger.error(f"Помилка отримання стрічки UkraineAlarmSignal: {e}")
        return None
