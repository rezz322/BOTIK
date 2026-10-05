import json
import os
import re
import logging
from config import SEEN_POSTS_FILE

logger = logging.getLogger(__name__)


def normalize_url(url: str) -> str:
    """
    Приводить URL Facebook до єдиного стандарту, прибираючи mibextid, rdid тощо,
    щоб зміна параметрів посилання не скидала збережений ID поста.
    """
    url = url.strip()
    match = re.search(r"id=(\d+)", url)
    if match:
        return f"https://www.facebook.com/profile.php?id={match.group(1)}"
    return url.split("?")[0]


class Storage:
    def __init__(self, filename=SEEN_POSTS_FILE):
        self.filename = filename
        self.last_posts = {}  # { normalized_url: last_post_id }
        self.load()

    def load(self):
        if os.path.exists(self.filename):
            try:
                with open(self.filename, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if "last_posts" in data and isinstance(data["last_posts"], dict):
                        self.last_posts = {
                            normalize_url(k): str(v)
                            for k, v in data["last_posts"].items()
                        }
                    elif "seen_posts" in data and isinstance(data["seen_posts"], list):
                        self.last_posts = {}
                    logger.info(f"💾 Завантажено збережені останні пости: {self.last_posts}")
            except Exception as e:
                logger.error(f"Помилка зчитування {self.filename}: {e}")
                self.last_posts = {}
        else:
            self.last_posts = {}

    def get_last_post_id(self, url: str) -> str | None:
        """Отримує ID останнього відправленого поста для URL."""
        return self.last_posts.get(normalize_url(url))

    def set_last_post_id(self, url: str, post_id: str):
        """Оновлює ID останнього поста."""
        self.last_posts[normalize_url(url)] = str(post_id)
        self.save()

    def save(self):
        try:
            with open(self.filename, "w", encoding="utf-8") as f:
                json.dump({"last_posts": self.last_posts}, f, ensure_ascii=False, indent=2)
        except Exception as e:
            logger.error(f"Помилка збереження бази у {self.filename}: {e}")
