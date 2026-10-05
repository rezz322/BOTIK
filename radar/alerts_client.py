# -*- coding: utf-8 -*-
import logging
from radar.utils import MONITORED_REGIONS

logger = logging.getLogger("AlertsClient")


class AlertsClient:
    """
    Клієнт перевірки статусу повітряної тривоги.
    Використовує узгодження статусів від прямих API eRadar та КУПОЛ
    із резервним джерелом alerts.in.ua.
    """

    def __init__(self, session, eradar_client=None, kupol_client=None):
        self.session = session
        self.eradar_client = eradar_client
        self.kupol_client = kupol_client

    def _check_alerts_in_ua_for_region(self, region_cfg: dict, cached_md: str = None) -> bool | None:
        """Резервна перевірка через alerts.in.ua."""
        text = cached_md
        if text is None:
            try:
                r = self.session.get("https://api.alerts.in.ua/v3/alerts/active.md", impersonate="chrome124", timeout=10)
                if r.status_code == 200:
                    text = r.text
            except Exception as e:
                logger.error(f"Помилка запиту до alerts.in.ua: {e}")
                return None

        if not text:
            return None

        sec3_idx = text.find("## 3. CURRENT WARNING STATUS")
        sec4_idx = text.find("## 4.", sec3_idx) if sec3_idx != -1 else -1
        sec3 = text[sec3_idx:sec4_idx] if sec3_idx != -1 and sec4_idx != -1 else text[sec3_idx:]

        oblast_keys = [k.lower() for k in region_cfg.get("oblast_keywords", [])]
        raion_keys = [k.lower() for k in region_cfg.get("raion_keywords", [])]

        in_oblast = False
        in_raion = False

        for para in sec3.split("\n\n"):
            para_s = para.strip().lower()
            if any(k in para_s for k in oblast_keys):
                in_oblast = True
                if any(rk in para_s for rk in raion_keys) or "all areas" in para_s or "всі райони" in para_s or "whole oblast" in para_s:
                    in_raion = True
                    break

        if in_oblast:
            return in_raion
        return False

    def check_alarms_for_regions(self, regions: dict = None) -> dict[str, bool]:
        """
        Перевіряє статус повітряної тривоги для всіх моніторингових регіонів (Сарни тощо).
        Логіка:
          1. Запитує прямий API eRadar (/api/alerts)
          2. Запитує прямий API КУПОЛ (/api/alerts/active)
          3. Якщо хоча б один із сервісів фіксує активну тривогу для району/області -> True.
          4. Якщо обидва підтверджують відсутність тривоги -> False (ВІДБІЙ).
          5. Якщо один із сервісів недоступний, використовується інший, або резервний alerts.in.ua.
        """
        if regions is None:
            regions = MONITORED_REGIONS

        results = {}
        alerts_md_cached = None

        for r_id, r_cfg in regions.items():
            r_name = r_cfg.get("short_name", r_id)
            eradar_status = None
            kupol_status = None

            # 1. Пряма перевірка eRadar
            if self.eradar_client:
                eradar_status = self.eradar_client.check_alarm_for_region(r_cfg)

            # 2. Пряма перевірка КУПОЛ
            if self.kupol_client:
                kupol_status = self.kupol_client.check_alarm_for_region(r_cfg)

            # 3. Визначення фінального статусу
            final_status = None

            # Якщо хоча б одне джерело повідомляє про тривогу
            if eradar_status is True or kupol_status is True:
                final_status = True
            # Якщо обидва сервіси активні і повідомляють про відбій
            elif eradar_status is False and kupol_status is False:
                final_status = False
            # Якщо доступний лише eRadar
            elif eradar_status is not None and kupol_status is None:
                final_status = eradar_status
            # Якщо доступний лише КУПОЛ
            elif kupol_status is not None and eradar_status is None:
                final_status = kupol_status
            else:
                # Обидва сервіси повернули помилку (None) -> використовуємо резервний alerts.in.ua
                res_backup = self._check_alerts_in_ua_for_region(r_cfg, cached_md=alerts_md_cached)
                final_status = res_backup if res_backup is not None else False

            results[r_id] = bool(final_status)
            logger.debug(
                f"[{r_name}] Статус тривоги: {results[r_id]} "
                f"(eRadar: {eradar_status}, КУПОЛ: {kupol_status})"
            )

        return results

    def check_alarm_for_region(self, region_cfg: dict) -> bool:
        """Перевіряє тривогу для одного обраного регіону."""
        res = self.check_alarms_for_regions({region_cfg["id"]: region_cfg})
        return res.get(region_cfg["id"], False)

    def check_sarny_alarm(self) -> bool:
        """Сумісність зі старим кодом."""
        return self.check_alarm_for_region(MONITORED_REGIONS["sarny"])
