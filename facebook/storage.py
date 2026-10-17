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
        self.seen_ids = {}    # { normalized_url: set_of_post_ids }
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
                    if "seen_ids" in data and isinstance(data["seen_ids"], dict):
                        self.seen_ids = {
                            normalize_url(k): set(map(str, v))
                            for k, v in data["seen_ids"].items()
                        }
                    else:
                        for k, v in self.last_posts.items():
                            self.seen_ids.setdefault(k, set()).add(v)

                    logger.info(f"💾 Завантажено збережені останні пости: {self.last_posts}")
            except Exception as e:
                logger.error(f"Помилка зчитування {self.filename}: {e}")
                self.last_posts = {}
                self.seen_ids = {}
        else:
            self.last_posts = {}
            self.seen_ids = {}

    def get_last_post_id(self, url: str) -> str | None:
        """Отримує ID останнього відправленого поста для URL."""
        return self.last_posts.get(normalize_url(url))

    def is_seen(self, url: str, post_id: str) -> bool:
        """Перевіряє, чи публікувався вже цей пост."""
        norm = normalize_url(url)
        return str(post_id) in self.seen_ids.get(norm, set()) or self.last_posts.get(norm) == str(post_id)

    def mark_seen(self, url: str, post_id: str):
        """Позначає пост як переглянутий і збережений."""
        norm = normalize_url(url)
        pid = str(post_id)
        self.last_posts[norm] = pid
        self.seen_ids.setdefault(norm, set()).add(pid)
        self.save()

    def set_last_post_id(self, url: str, post_id: str):
        """Оновлює ID останнього поста."""
        self.mark_seen(url, post_id)

    def save(self):
        try:
            seen_dict = {k: list(v)[-100:] for k, v in self.seen_ids.items()}
            with open(self.filename, "w", encoding="utf-8") as f:
                json.dump(
                    {"last_posts": self.last_posts, "seen_ids": seen_dict},
                    f,
                    ensure_ascii=False,
                    indent=2,
                )
        except Exception as e:
            logger.error(f"Помилка збереження бази у {self.filename}: {e}")
