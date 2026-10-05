# -*- coding: utf-8 -*-
import re
import html
import json
import logging
from typing import List, Dict, Any, Optional
import requests
from config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)


def escape_html(text: str) -> str:
    """Екранує спеціальні HTML-символи для безпечної відправки в Telegram."""
    return html.escape(text or "")


class TelegramSender:
    def __init__(self, token: str = TELEGRAM_BOT_TOKEN, channel: str = TELEGRAM_CHAT_ID):
        self.token = token
        self.channel = channel
        self.api_url = f"https://api.telegram.org/bot{self.token}"

    def send_post(self, post: Dict[str, Any], thread_id: Optional[int] = None) -> bool:
        """
        Відправляє пост у відповідну гілку (thread_id) або канал.
        """
        if not self.token:
            logger.error("❌ TELEGRAM_BOT_TOKEN не заданий! Додайте токен у файл .env")
            return False

        text = post.get("text", "").strip()
        permalink = post.get("permalink", "")
        images = post.get("images", [])

        link_html = f'\n\n🔗 <a href="{permalink}">Читати повністю у Facebook</a>' if permalink else ""

        try:
            if images:
                max_text_len = 1024 - len(link_html) - 10
                if len(text) > max_text_len:
                    caption = escape_html(text[:max_text_len].rsplit(" ", 1)[0]) + "..." + link_html
                else:
                    caption = escape_html(text) + link_html

                if len(images) == 1:
                    return self._send_single_photo(images[0], caption, thread_id=thread_id)
                else:
                    return self._send_album(images, caption, thread_id=thread_id)
            else:
                full_text = escape_html(text) + link_html
                return self._send_text_message(full_text, thread_id=thread_id)
        except Exception as e:
            logger.error(f"Помилка при відправці посту в Telegram: {e}", exc_info=True)
            return False

    def _send_text_message(self, text_html: str, thread_id: Optional[int] = None) -> bool:
        """Відправляє текстове повідомлення в конкретну гілку (thread_id) із захистом від помилок парсингу."""
        url = f"{self.api_url}/sendMessage"
        if len(text_html) > 4000:
            text_html = text_html[:3900].rsplit(" ", 1)[0] + "...\n(текст скорочено)"

        payload = {
            "chat_id": self.channel,
            "text": text_html,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }
        if thread_id is not None:
            payload["message_thread_id"] = thread_id

        try:
            res = requests.post(url, json=payload, timeout=20)
            success = self._handle_telegram_response(res, f"sendMessage (thread={thread_id})")
            if not success and res.status_code == 400 and payload.get("parse_mode") == "HTML":
                # Резервна відправка: якщо Telegram відхилив через помилку валідації HTML-тегів
                logger.warning("⚠️ Помилка HTML в Telegram, резервна відправка чистим текстом без форматування...")
                plain_text = re.sub(r"<[^>]+>", "", text_html)
                payload_fallback = {
                    "chat_id": self.channel,
                    "text": plain_text,
                    "disable_web_page_preview": False,
                }
                if thread_id is not None:
                    payload_fallback["message_thread_id"] = thread_id
                res_fb = requests.post(url, json=payload_fallback, timeout=20)
                return self._handle_telegram_response(res_fb, f"sendMessage_plain (thread={thread_id})")
            return success
        except Exception as e:
            logger.error(f"Виняток при відправці повідомлення в Telegram: {e}")
            return False

    def _send_single_photo(self, image_url: str, caption: str, thread_id: Optional[int] = None) -> bool:
        """Відправляє фото з підписом в конкретну гілку (thread_id)."""
        url = f"{self.api_url}/sendPhoto"
        payload = {
            "chat_id": self.channel,
            "photo": image_url,
            "caption": caption,
            "parse_mode": "HTML",
        }
        if thread_id is not None:
            payload["message_thread_id"] = thread_id

        try:
            res = requests.post(url, json=payload, timeout=25)
            return self._handle_telegram_response(res, f"sendPhoto (thread={thread_id})")
        except Exception as e:
            logger.error(f"Виняток при відправці фото в Telegram: {e}")
            return False

    def _send_album(self, image_urls: List[str], caption: str, thread_id: Optional[int] = None) -> bool:
        """Відправляє медіа-альбом в конкретну гілку (thread_id)."""
        url = f"{self.api_url}/sendMediaGroup"
        media_group = []
        for idx, img in enumerate(image_urls[:10]):
            media_item: Dict[str, Any] = {
                "type": "photo",
                "media": img,
            }
            if idx == 0:
                media_item["caption"] = caption
                media_item["parse_mode"] = "HTML"
            media_group.append(media_item)

        payload = {
            "chat_id": self.channel,
            "media": json.dumps(media_group),
        }
        if thread_id is not None:
            payload["message_thread_id"] = thread_id

        try:
            res = requests.post(url, data=payload, timeout=30)
            success = self._handle_telegram_response(res, f"sendMediaGroup (thread={thread_id})")
            if not success:
                logger.warning("Альбом не надіслано, надсилаємо перше фото...")
                return self._send_single_photo(image_urls[0], caption, thread_id=thread_id)
            return success
        except Exception as e:
            logger.error(f"Виняток при відправці альбому в Telegram: {e}")
            return False

    def _handle_telegram_response(self, res: requests.Response, action_name: str) -> bool:
        try:
            data = res.json()
            if data.get("ok"):
                logger.info(f"🚀 Успішно надіслано в Telegram [{action_name}] -> {self.channel}")
                return True
            else:
                logger.error(f"Помилка Telegram API [{action_name}] ({res.status_code}): {data.get('description')}")
                return False
        except Exception as e:
            logger.error(f"Некоректна відповідь Telegram [{action_name}]: {res.text} ({e})")
            return False
