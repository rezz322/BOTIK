import json
import re
import logging
from typing import List, Dict, Any, Optional
from curl_cffi import requests
from config import IMPERSONATE_BROWSER, FB_COOKIES

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "uk-UA,uk;q=0.9,ru;q=0.8,en-US;q=0.7,en;q=0.6",
    "Cache-Control": "max-age=0",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
}


def parse_cookie_string(cookie_str: str) -> dict:
    cookies = {}
    if not cookie_str:
        return cookies
    for part in cookie_str.split(";"):
        part = part.strip()
        if "=" in part:
            k, v = part.split("=", 1)
            cookies[k.strip()] = v.strip()
    return cookies


class FacebookParser:
    def __init__(self, browser_fingerprint: str = IMPERSONATE_BROWSER):
        self.browser_fingerprint = browser_fingerprint
        self.session = requests.Session()
        self.session.headers.update(DEFAULT_HEADERS)
        if FB_COOKIES:
            self.session.cookies.update(parse_cookie_string(FB_COOKIES))

    def fetch_profile_posts(self, profile_url: str) -> List[Dict[str, Any]]:
        """
        Відправляє HTTP запит з TLS-фінгерпринтом браузера (curl_cffi)
        і парсить пости з профілю Facebook.
        """
        logger.info(f"🌐 Отримання сторінки (Fingerprint: {self.browser_fingerprint}): {profile_url}")
        try:
            resp = self.session.get(
                profile_url,
                impersonate=self.browser_fingerprint,
                timeout=30,
            )
            if resp.status_code != 200:
                logger.warning(f"Facebook повернув статус {resp.status_code} для {profile_url}")
                return []

            posts = self._extract_posts_from_html(resp.text, profile_url)
            logger.info(f"✅ Знайдено {len(posts)} постів для {profile_url}")
            return posts

        except Exception as e:
            logger.error(f"Помилка при запиті Facebook {profile_url}: {e}", exc_info=True)
            return []

    def fetch_latest_post(self, profile_url: str) -> Optional[Dict[str, Any]]:
        """
        Отримує тільки один найновіший (останній) пост для даного профілю.
        """
        posts = self.fetch_profile_posts(profile_url)
        if not posts:
            return None
        posts.sort(key=lambda p: int(p.get("creation_time") or 0), reverse=True)
        return posts[0]

    def _extract_posts_from_html(self, html: str, fallback_url: str) -> List[Dict[str, Any]]:
        """
        Шукає JSON структури Relay Comet у середині <script type="application/json">
        і витягує тексти, посилання та медіа постів.
        """
        scripts = re.findall(r'<script type="application/json"[^>]*>(.*?)</script>', html, re.DOTALL)
        posts: List[Dict[str, Any]] = []
        seen_ids = set()

        def search_stories(node: Any) -> list:
            found = []
            if isinstance(node, dict):
                if node.get("__typename") == "Story" and node.get("post_id"):
                    found.append(node)
                for v in node.values():
                    found.extend(search_stories(v))
            elif isinstance(node, list):
                for item in node:
                    found.extend(search_stories(item))
            return found

        for script_content in scripts:
            if '"post_id"' not in script_content and '"creation_time"' not in script_content:
                continue

            try:
                data = json.loads(script_content)
                stories = search_stories(data)

                for story in stories:
                    post_id = str(story.get("post_id", ""))
                    if not post_id or post_id in seen_ids:
                        continue
                    seen_ids.add(post_id)

                    # 1. Посилання на пост
                    permalink = story.get("permalink_url")
                    if not permalink:
                        metadata = (
                            story.get("comet_sections", {})
                            .get("context_layout", {})
                            .get("story", {})
                            .get("comet_sections", {})
                            .get("metadata", [])
                        )
                        for m in metadata:
                            st = m.get("story", {})
                            if st.get("url"):
                                permalink = st.get("url")
                                break

                    if not permalink:
                        permalink = f"https://www.facebook.com/{post_id}"

                    # 2. Текст публікації
                    text_content = self._extract_best_text(story)

                    # 3. Фото / Медіа
                    images = self._extract_images(story)

                    # 4. Час публікації
                    creation_time = story.get("creation_time")

                    posts.append({
                        "post_id": post_id,
                        "permalink": permalink,
                        "text": text_content,
                        "images": images,
                        "creation_time": creation_time,
                        "source_url": fallback_url
                    })
            except Exception:
                continue

        return posts

    def _extract_best_text(self, story: dict) -> str:
        """
        Знаходить найбільш змістовний текст повідомлення посту.
        """
        found_texts = []

        def find_texts(obj: Any):
            if isinstance(obj, dict):
                if "message" in obj and isinstance(obj["message"], dict):
                    msg_txt = obj["message"].get("text")
                    if isinstance(msg_txt, str) and msg_txt.strip():
                        found_texts.append(msg_txt.strip())

                for k, v in obj.items():
                    if k == "text" and isinstance(v, str) and len(v.strip()) > 10:
                        found_texts.append(v.strip())
                    else:
                        find_texts(v)
            elif isinstance(obj, list):
                for item in obj:
                    find_texts(item)

        find_texts(story)

        ui_keywords = [
            "Поділитися", "Коментувати", "Подобається", "Вподобати",
            "Facebook", "Залишити коментар", "Написати коментар"
        ]
        clean_texts = [
            t for t in found_texts
            if not any(kw in t for kw in ui_keywords) and len(t) > 15
        ]

        if clean_texts:
            return max(clean_texts, key=len)
        elif found_texts:
            return max(found_texts, key=len)
        return ""

    def _extract_images(self, story: dict) -> List[str]:
        """
        Витягує посилання на повнорозмірні фотографії до посту.
        """
        found_images = []

        def find_uris(obj: Any):
            if isinstance(obj, dict):
                if "uri" in obj and isinstance(obj["uri"], str):
                    uri = obj["uri"]
                    if ("fbcdn" in uri or "scontent" in uri) and not any(
                        bad in uri for bad in ["p50x50", "s50x50", "cp0_dst-jpg", "p100x100"]
                    ):
                        found_images.append(uri)
                for v in obj.values():
                    find_uris(v)
            elif isinstance(obj, list):
                for item in obj:
                    find_uris(item)

        find_uris(story)
        unique_images = list(dict.fromkeys(found_images))
        return unique_images[:10]
