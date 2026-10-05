import math
import sys
from datetime import datetime, timezone
from curl_cffi import requests

sys.stdout.reconfigure(encoding="utf-8")

# Координати Сарн
SARNY_LAT = 51.3378
SARNY_LNG = 26.6344
MAX_DISTANCE_KM = 55.0  # Радіус охоплення Сарненського району

SARNY_KEYWORDS = [
    "сарненський"
]

def haversine_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def get_sarny_info():
    session = requests.Session()
    headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/124.0.0.0 Safari/537.36"}
    
    # 1. Перевірка статусу тривоги
    alerts_res = session.get("https://eradar.app/api/alerts", headers=headers, impersonate="chrome124")
    alerts_data = alerts_res.json() if alerts_res.status_code == 200 else {}
    active_alerts = alerts_data.get("active", [])
    
    is_rivne_alert = any("рівнен" in x.lower() for x in active_alerts)
    alert_status = "🔴 ТРИВОГА" if is_rivne_alert else "🟢 ВІДБІЙ (тривоги немає)"

    # 2. Перевірка активних загроз (Dangers)
    dangers_res = session.get("https://eradar.app/api/dangers", headers=headers, impersonate="chrome124")
    dangers_data = dangers_res.json().get("dangers", []) if dangers_res.status_code == 200 else []
    
    sarny_dangers = []
    for d in dangers_data:
        name = d.get("canonical_name", "").lower()
        lat = d.get("lat")
        lng = d.get("lng")
        dist = haversine_km(SARNY_LAT, SARNY_LNG, lat, lng) if (lat and lng) else 9999
        
        matches_name = any(k in name for k in SARNY_KEYWORDS)
        in_range = dist <= MAX_DISTANCE_KM
        
        if matches_name or in_range:
            sarny_dangers.append({
                "id": d.get("id"),
                "threat_type": d.get("threat_type"),
                "canonical_name": d.get("canonical_name"),
                "distance_km": round(dist, 1),
                "channel": d.get("channel"),
                "excerpt": d.get("message_excerpt"),
                "expires_at": d.get("expires_at"),
                "first_seen": d.get("first_seen")
            })

    # 3. Перевірка стрічки моніторингу (Feed)
    feed_res = session.get("https://eradar.app/api/feed?limit=100", headers=headers, impersonate="chrome124")
    feed_data = feed_res.json().get("feed", []) if feed_res.status_code == 200 else []
    
    sarny_feed = []
    for item in feed_data:
        text = item.get("text", "")
        text_lower = text.lower()
        mentions = item.get("mentions", [])
        
        match = any(k in text_lower for k in SARNY_KEYWORDS) or any(
            any(k in (m.get("place_query") or "").lower() for k in SARNY_KEYWORDS)
            for m in mentions
        )
        if match:
            sarny_feed.append(item)

    return {
        "alert_status": alert_status,
        "is_alert": is_rivne_alert,
        "fetched_at": alerts_data.get("fetched_at"),
        "sarny_dangers": sarny_dangers,
        "sarny_feed": sarny_feed,
        "total_active_dangers_ukraine": len(dangers_data)
    }

if __name__ == "__main__":
    info = get_sarny_info()
    print("==================================================")
    print("📍 СТАН ДЛЯ САРНЕНСЬКОГО РАЙОНУ (eRadar):")
    print(f"Статус тривоги: {info['alert_status']}")
    print(f"Час опитування: {info['fetched_at']}")
    print(f"Всього активних цілей в Україні зараз: {info['total_active_dangers_ukraine']}")
    print("==================================================")
    
    print(f"\n🎯 Прямі загрози в зоні Сарненського району: {len(info['sarny_dangers'])}")
    for d in info["sarny_dangers"]:
        print(f"- Тип: {d['threat_type']}, Місце: {d['canonical_name']}, Відстань: {d['distance_km']} км")
        print(f"  Джерело: @{d['channel']}, Текст: {d['excerpt']}")
        print(f"  Діє до: {d['expires_at']}")

    print(f"\n📡 Згадки у моніторингових каналах: {len(info['sarny_feed'])}")
    for f in info["sarny_feed"][:5]:
        print(f"- [{f['msg_date']}] @{f['channel']}: {f['text']}")
