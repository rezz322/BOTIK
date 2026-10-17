# -*- coding: utf-8 -*-
import re
import ssl
import hashlib
import logging
from html import unescape
from typing import Dict, Any, List, Optional
from datetime import datetime

logger = logging.getLogger("PowerClient")

# URL офіційної сторінки графіків відключень ПрАТ «Рівнеобленерго» та глобального дзеркала Alerts.org.ua
ALERTS_ORG_UA_URL = "https://alerts.org.ua/rivnenska-oblast/"
ROE_DISCONNECTIONS_URL = "https://www.roe.vsei.ua/disconnections/"
ROE_OBLAST_QUEUES_PDF = "https://www.roe.vsei.ua/wp-content/uploads/2026/07/GPV_cherga_Rivnenska_oblast.pdf"

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "uk-UA,uk;q=0.9,en-US;q=0.8,en;q=0.7",
}


class RivneoblenergoClient:
    """
    Клієнт для отримання актуальних графіків погодинних відключень (ГПВ)
    по місту Сарни та Рівненській області (alerts.org.ua / roe.vsei.ua).
    """

    def __init__(self, timeout: int = 12):
        self.timeout = timeout

    def fetch_page_html(self) -> str:
        """Отримує актуальний HTML графіків з підтримкою alerts.org.ua та roe.vsei.ua."""
        import sys
        logger.info(f"   🌐 Запит графіка з {ALERTS_ORG_UA_URL}...")
        sys.stdout.flush()

        # 1. Запит до alerts.org.ua через urllib (глобальний Cloudflare CDN, без блокування іноземних серверів)
        try:
            import urllib.request
            req = urllib.request.Request(ALERTS_ORG_UA_URL, headers=DEFAULT_HEADERS)
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                body = resp.read().decode("utf-8", errors="ignore")
                if len(body) > 1000 and "group-name" in body:
                    logger.info(f"   ✅ Графік успішно отримано з alerts.org.ua ({len(body)} байт)")
                    sys.stdout.flush()
                    return body
        except Exception as e:
            logger.warning(f"   ⚠️ alerts.org.ua (urllib): {e}")
        sys.stdout.flush()

        # 2. Системний curl до alerts.org.ua
        try:
            import subprocess
            cmd = ["curl", "-s", "-L", "-k", "-m", str(self.timeout), "-A", DEFAULT_HEADERS["User-Agent"], ALERTS_ORG_UA_URL]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout + 2)
            if proc.returncode == 0 and len(proc.stdout) > 1000 and "group-name" in proc.stdout:
                logger.info("   ✅ Графік успішно отримано через системний curl з alerts.org.ua")
                sys.stdout.flush()
                return proc.stdout
        except Exception as e:
            logger.debug(f"curl to alerts.org.ua failed: {e}")
        sys.stdout.flush()

        # 3. Резерв: curl_cffi до alerts.org.ua
        try:
            from curl_cffi import requests as cffi_requests
            res = cffi_requests.get(ALERTS_ORG_UA_URL, headers=DEFAULT_HEADERS, impersonate="chrome124", timeout=self.timeout)
            if res.status_code == 200 and len(res.text) > 1000 and "group-name" in res.text:
                logger.info("   ✅ Графік успішно отримано з alerts.org.ua (curl_cffi)")
                sys.stdout.flush()
                return res.text
        except Exception as e:
            logger.debug(f"curl_cffi to alerts.org.ua failed: {e}")
        sys.stdout.flush()

        # 4. Резервний запит напряму до roe.vsei.ua
        logger.info(f"   🌐 Резервний запит до {ROE_DISCONNECTIONS_URL}...")
        sys.stdout.flush()
        try:
            import subprocess
            cmd = ["curl", "-s", "-L", "-k", "-m", str(self.timeout), "-A", DEFAULT_HEADERS["User-Agent"], ROE_DISCONNECTIONS_URL]
            proc = subprocess.run(cmd, capture_output=True, text=True, timeout=self.timeout + 2)
            if proc.returncode == 0 and len(proc.stdout) > 1000:
                logger.info("   ✅ Отримано HTML з roe.vsei.ua")
                sys.stdout.flush()
                return proc.stdout
        except Exception as e:
            logger.warning(f"   ⚠️ roe.vsei.ua не відповів: {e}")
        sys.stdout.flush()

        logger.error("❌ Не вдалося отримати графіки з alerts.org.ua та roe.vsei.ua!")
        sys.stdout.flush()
        return ""

    def parse_alerts_org_ua(self, html: str) -> Dict[str, Any]:
        """Парсить дані графіків відключень із сайту alerts.org.ua/rivnenska-oblast/"""
        date_match = re.search(r"(\d{2}\.\d{2}\.\d{4})", html)
        date_str = date_match.group(1) if date_match else datetime.now().strftime("%d.%m.%Y")

        is_emergency = "аварійні" in html.lower() or "екстрені" in html.lower()
        subqueues = [
            "1.1", "1.2", "2.1", "2.2", "3.1", "3.2",
            "4.1", "4.2", "5.1", "5.2", "6.1", "6.2"
        ]
        status_by_subqueue: Dict[str, str] = {}
        has_outages = False

        for sq in subqueues:
            pattern = rf'<b class="group-name">[^<]*{re.escape(sq)}</b>(.*?)</div>\s*</div>\s*</div>'
            m = re.search(pattern, html, re.DOTALL)
            if m:
                block = m.group(1)
                offs = re.findall(r'(\d{2}:\d{2}\s*[-–—]\s*\d{2}:\d{2})\s*<b class="off"', block)
                if offs:
                    status_by_subqueue[sq] = ", ".join(offs)
                    has_outages = True
                else:
                    status_by_subqueue[sq] = "Без обмежень"
            else:
                status_by_subqueue[sq] = "Без обмежень"

        hash_str = hashlib.md5(f"{date_str}_{str(status_by_subqueue)}_{is_emergency}".encode("utf-8")).hexdigest()

        return {
            "success": True,
            "hash": hash_str,
            "is_emergency": is_emergency,
            "subqueues": subqueues,
            "days": [
                {
                    "date": date_str,
                    "status_by_subqueue": status_by_subqueue,
                    "has_outages": has_outages,
                    "is_pending": False,
                }
            ],
            "raw_rows": [],
            "pdf_link": ROE_OBLAST_QUEUES_PDF,
            "source": "alerts.org.ua",
        }

    def parse_schedule(self, html: Optional[str] = None) -> Dict[str, Any]:
        """
        Парсить графік погодинних відключень (ГПВ) для Рівненської області та Сарн.
        Підтримує формати alerts.org.ua та roe.vsei.ua.
        """
        if not html:
            html = self.fetch_page_html()

        if not html:
            return {"success": False, "error": "fetch_failed"}

        # Якщо HTML з alerts.org.ua
        if "group-name" in html or "alerts.org.ua" in html:
            return self.parse_alerts_org_ua(html)

        table_match = re.search(r"<table[^>]*>(.*?)</table>", html, re.DOTALL)
        if not table_match:
            logger.warning("Таблицю графіків відключень на сторінці не знайдено.")
            return {"success": False, "error": "table_not_found"}

        table_content = table_match.group(1)
        raw_rows = re.findall(r"<tr[^>]*>(.*?)</tr>", table_content, re.DOTALL)

        rows_data: List[List[str]] = []
        for r in raw_rows:
            cols = [
                unescape(re.sub(r"<[^>]+>", "", c)).strip()
                for c in re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", r, re.DOTALL)
            ]
            if any(cols):
                rows_data.append(cols)

        if len(rows_data) < 4:
            logger.warning(f"Замало рядків у таблиці графіків: {len(rows_data)}")
            return {"success": False, "error": "insufficient_rows"}

        # Шукаємо рядок із номерами підчерг (1.1, 1.2, ..., 6.2)
        subqueues_row_idx = None
        subqueues: List[str] = []
        for idx, row in enumerate(rows_data):
            found_sq = [c for c in row if re.match(r"^\d\.\d$", c)]
            if len(found_sq) >= 6:
                subqueues_row_idx = idx
                # Перша колонка зазвичай "Підчерга", тому беремо ті, що відповідають патерну
                subqueues = [c for c in row if re.match(r"^\d\.\d$", c)]
                break

        if subqueues_row_idx is None or not subqueues:
            # Дефолтний список підчерг Рівнеобленерго
            subqueues = ["1.1", "1.2", "2.1", "2.2", "3.1", "3.2", "4.1", "4.2", "5.1", "5.2", "6.1", "6.2"]
            subqueues_row_idx = 3

        # Парсимо дні (рядки після підчерг)
        days_data: List[Dict[str, Any]] = []
        for row in rows_data[subqueues_row_idx + 1:]:
            if not row:
                continue

            first_col = row[0].strip()
            # Шукаємо дату у форматі ДД.ММ.РРРР
            date_match = re.search(r"(\d{1,2}\.\d{1,2}\.\d{4})", first_col)
            if not date_match:
                continue

            date_str = date_match.group(1)
            intervals = row[1:]

            status_by_subqueue: Dict[str, str] = {}
            for sq_idx, sq in enumerate(subqueues):
                if sq_idx < len(intervals):
                    val = intervals[sq_idx].strip()
                    status_by_subqueue[sq] = val if val else "Без обмежень"
                else:
                    status_by_subqueue[sq] = "Без обмежень"

            has_outages = any(
                v not in ("Без обмежень", "", "Очікується", "-")
                for v in status_by_subqueue.values()
            )
            is_pending = all(v == "Очікується" for v in status_by_subqueue.values())

            days_data.append({
                "date": date_str,
                "status_by_subqueue": status_by_subqueue,
                "has_outages": has_outages,
                "is_pending": is_pending,
            })

        # Перевірка наявності оголошення про екстрені / аварійні відключення
        is_emergency = False
        emergency_notice = None

        emergency_patterns = [
            r"(введено\s+(?:екстрені|аварійні)\s+відключення)",
            r"((?:екстрені|аварійні)\s+відключення\s+(?:введено|застосовано|діють))",
            r"(графіки\s+(?:погодинних\s+відключень\s+)?(?:тимчасово\s+)?(?:не\s+діють|скасовано|призупинено))",
            r"(застосовано\s+(?:спеціальні\s+)?графіки\s+аварійних\s+відключень|\bСГАВ\b|\bГАВ\b)",
        ]

        text_before_table = html[:table_match.start()] if table_match else html
        clean_header_text = " ".join(unescape(re.sub(r"<[^>]+>", " ", text_before_table)).split())

        for pat in emergency_patterns:
            m = re.search(pat, clean_header_text, re.IGNORECASE)
            if m:
                is_emergency = True
                emergency_notice = m.group(0)
                break

        # Обчислюємо хеш таблиці для точного відстеження змін
        raw_repr = "|".join(
            f"{d['date']}:" + ",".join(f"{k}={v}" for k, v in sorted(d["status_by_subqueue"].items()))
            for d in days_data
        ) + f"|emergency:{is_emergency}"
        content_hash = hashlib.md5(raw_repr.encode("utf-8")).hexdigest()

        return {
            "success": True,
            "hash": content_hash,
            "subqueues": subqueues,
            "days": days_data,
            "is_emergency": is_emergency,
            "emergency_notice": emergency_notice,
            "pdf_link": ROE_OBLAST_QUEUES_PDF,
            "source_url": ROE_DISCONNECTIONS_URL,
            "parsed_at": datetime.now().isoformat(),
        }
