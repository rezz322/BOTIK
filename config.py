import os
from dotenv import load_dotenv

# Завантажуємо налаштування з .env
load_dotenv()

# Telegram налаштування
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHANNEL = os.getenv("TELEGRAM_CHANNEL", "@GG_WPasdfasdf")

# ID чату або групи (для гілок форуму використовується ID групи обговорення)
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", TELEGRAM_CHANNEL)

# ID гілок (message_thread_id) для окремих тем
def _parse_thread_id(val):
    if val and str(val).strip().lstrip("-").isdigit():
        return int(str(val).strip())
    return None

THREAD_ID_FB_1 = _parse_thread_id(os.getenv("THREAD_ID_FB_1"))              # гілка "Фейсбук 1"
THREAD_ID_FB_2 = _parse_thread_id(os.getenv("THREAD_ID_FB_2"))              # гілка "Фейсбук 2"
THREAD_ID_ALERTS = _parse_thread_id(os.getenv("THREAD_ID_ALERTS"))          # гілка "Тривога" (Сарни)

# Список посилань на профілі Facebook для моніторингу
TARGET_URLS = [
    os.getenv(
        "FB_URL_1",
        "https://www.facebook.com/profile.php?id=100083009785339",
    ),
    os.getenv(
        "FB_URL_2",
        "https://www.facebook.com/profile.php?id=100064698822458",
    ),
]

# Словник прив'язки URL до відповідної гілки
URL_TO_THREAD = {
    TARGET_URLS[0]: THREAD_ID_FB_1,
    TARGET_URLS[1]: THREAD_ID_FB_2,
}

# Інтервал перевірки (в годинах)
CHECK_INTERVAL_HOURS = int(os.getenv("CHECK_INTERVAL_HOURS", "1"))

# Чи відправляти пости, знайдені при першому запуску
SEND_INITIAL_POSTS = os.getenv("SEND_INITIAL_POSTS", "True").lower() in ("true", "1", "yes")

# Файл збереження вже надісланих постів
SEEN_POSTS_FILE = os.getenv("SEEN_POSTS_FILE", "seen_posts.json")

# Опціональні Facebook cookies
FB_COOKIES = os.getenv("FB_COOKIES", "")

# Версія браузера для TLS Fingerprint (curl_cffi)
IMPERSONATE_BROWSER = os.getenv("IMPERSONATE_BROWSER", "chrome124")
