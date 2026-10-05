import logging

logger = logging.getLogger("AlertsClient")


class AlertsClient:
    """Клієнт перевірки статусу повітряної тривоги для Сарненського району."""

    def __init__(self, session, eradar_client=None, kupol_client=None):
        self.session = session
        self.eradar_client = eradar_client
        self.kupol_client = kupol_client

    def check_sarny_alarm(self) -> bool:
        """
        Перевіряє статус повітряної тривоги ВИКЛЮЧНО для Сарненського району:
        1. alerts.in.ua з районною деталізацією (основне джерело).
        2. @UkraineAlarmSignal у стрічці eRadar (запасне джерело 1).
        3. Районні тривоги КУПОЛ kupol.in.ua (запасне джерело 2).
        """
        # 1. Основне джерело: alerts.in.ua
        try:
            r = self.session.get("https://api.alerts.in.ua/v3/alerts/active.md", impersonate="chrome124", timeout=10)
            if r.status_code == 200:
                txt = r.text
                sec3_idx = txt.find("## 3. CURRENT WARNING STATUS")
                sec4_idx = txt.find("## 4.", sec3_idx) if sec3_idx != -1 else -1
                sec3 = txt[sec3_idx:sec4_idx] if sec3_idx != -1 and sec4_idx != -1 else txt[sec3_idx:]

                for para in sec3.split("\n\n"):
                    para_s = para.strip()
                    if "rivnenska oblast" in para_s.lower() or "рівненська область" in para_s.lower():
                        if "sarnen" in para_s.lower() or "сарненськ" in para_s.lower():
                            return True
                        elif "all areas" in para_s.lower() or "всі райони" in para_s.lower():
                            return True
                        else:
                            return False

                return False
        except Exception as e:
            logger.error(f"Помилка отримання районного статусу з alerts.in.ua: {e}")

        # 2. Запасне джерело 1: eRadar стрічка
        if self.eradar_client:
            res = self.eradar_client.check_alarm_signal_feed()
            if res is not None:
                return res

        # 3. Запасне джерело 2: КУПОЛ
        if self.kupol_client:
            res = self.kupol_client.check_sarny_alarm()
            if res is not None:
                return res

        return False
