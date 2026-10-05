import logging
from radar.utils import MONITORED_REGIONS

logger = logging.getLogger("AlertsClient")


class AlertsClient:
    """Клієнт перевірки статусу повітряної тривоги для моніторингових регіонів (Сарни, Одеса тощо)."""

    def __init__(self, session, eradar_client=None, kupol_client=None):
        self.session = session
        self.eradar_client = eradar_client
        self.kupol_client = kupol_client

    def check_alarms_for_regions(self, regions: dict = None) -> dict[str, bool]:
        """
        Перевіряє статус повітряної тривоги для всіх зазначених регіонів (Сарни, Одеса...).
        Отримує дані з alerts.in.ua за 1 спільний запит.
        """
        if regions is None:
            regions = MONITORED_REGIONS

        results = {r_id: False for r_id in regions}
        alerts_md_text = None

        # 1. Запит до alerts.in.ua
        try:
            r = self.session.get("https://api.alerts.in.ua/v3/alerts/active.md", impersonate="chrome124", timeout=10)
            if r.status_code == 200:
                alerts_md_text = r.text
        except Exception as e:
            logger.error(f"Помилка отримання районного статусу з alerts.in.ua: {e}")

        # Обробка кожного регіону
        for r_id, r_cfg in regions.items():
            found_status = None

            if alerts_md_text:
                sec3_idx = alerts_md_text.find("## 3. CURRENT WARNING STATUS")
                sec4_idx = alerts_md_text.find("## 4.", sec3_idx) if sec3_idx != -1 else -1
                sec3 = alerts_md_text[sec3_idx:sec4_idx] if sec3_idx != -1 and sec4_idx != -1 else alerts_md_text[sec3_idx:]

                oblast_keys = r_cfg.get("oblast_keywords", [])
                raion_keys = r_cfg.get("raion_keywords", [])

                in_oblast = False
                in_raion = False

                for para in sec3.split("\n\n"):
                    para_s = para.strip().lower()
                    if any(k in para_s for k in oblast_keys):
                        in_oblast = True
                        if any(rk in para_s for rk in raion_keys) or "all areas" in para_s or "всі райони" in para_s:
                            in_raion = True
                            break

                if in_oblast:
                    found_status = in_raion
                else:
                    found_status = False

            # Якщо alerts.in.ua не визначив або сталася помилка — перевіряємо запасні джерела
            if found_status is None:
                if self.eradar_client:
                    res_eradar = self.eradar_client.check_alarm_signal_for_region(r_cfg)
                    if res_eradar is not None:
                        found_status = res_eradar

            if found_status is None:
                if self.kupol_client:
                    res_kupol = self.kupol_client.check_alarm_for_region(r_cfg)
                    if res_kupol is not None:
                        found_status = res_kupol

            results[r_id] = bool(found_status)

        return results

    def check_alarm_for_region(self, region_cfg: dict) -> bool:
        """Перевіряє тривогу для одного обраного регіону."""
        res = self.check_alarms_for_regions({region_cfg["id"]: region_cfg})
        return res.get(region_cfg["id"], False)

    def check_sarny_alarm(self) -> bool:
        """Сумісність зі старим кодом."""
        return self.check_alarm_for_region(MONITORED_REGIONS["sarny"])
