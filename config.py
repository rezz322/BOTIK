# -*- coding: utf-8 -*-
import os
# Завантажуємо налаштування з .env
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# Telegram налаштування
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip().strip("'\"")
TELEGRAM_CHANNEL = os.getenv("TELEGRAM_CHANNEL", "@GG_WPasdfasdf").strip().strip("'\"")

# ID чату або групи (для гілок форуму використовується ID групи обговорення)
_raw_chat_id = os.getenv("TELEGRAM_CHAT_ID", TELEGRAM_CHANNEL).strip().strip("'\"")
try:
    TELEGRAM_CHAT_ID = int(_raw_chat_id)
except ValueError:
    TELEGRAM_CHAT_ID = _raw_chat_id

# ID гілок (message_thread_id) для окремих тем
def _parse_thread_id(val):
    if not val:
        return None
    cleaned = str(val).strip().strip("'\"")
    if cleaned.lstrip("-").isdigit():
        return int(cleaned)
    return None

THREAD_ID_FB_1 = _parse_thread_id(os.getenv("THREAD_ID_FB_1"))              # гілка "Фейсбук 1"
THREAD_ID_FB_2 = _parse_thread_id(os.getenv("THREAD_ID_FB_2"))              # гілка "Фейсбук 2"
THREAD_ID_ALERTS = _parse_thread_id(os.getenv("THREAD_ID_ALERTS"))          # гілка "Тривога" (Сарни / Радар)
THREAD_ID_POWER = _parse_thread_id(os.getenv("THREAD_ID_POWER"))            # гілка "Світло / Відключення" (Сарни)

# Налаштування моніторингу відключень електроенергії (Рівнеобленерго для Сарн):
POWER_POLL_INTERVAL = int(os.getenv("POWER_POLL_INTERVAL", "60"))           # Інтервал опитування графіків (секунди, 60 сек)
POWER_WARN_MINUTES = int(os.getenv("POWER_WARN_MINUTES", "10"))             # Попереджати за N хвилин до початку відключення (за замовчуванням 10 хв)
POWER_TARGET_SUBQUEUES = os.getenv("POWER_TARGET_SUBQUEUES", "all")         # Підчерги для відображення ('all' або '1.1,1.2')
SEND_INITIAL_POWER = os.getenv("SEND_INITIAL_POWER", "True").lower() in ("true", "1", "yes")
POWER_STATE_FILE = os.getenv("POWER_STATE_FILE", "power_state.json")        # Файл збереження стану графіків

# Налаштування моніторингу map.ukrainealarm.com:
RADAR_RADIUS_KM = float(os.getenv("RADAR_RADIUS_KM", "75"))  # Радіус виявлення цілей навколо Сарн та громад (км)
ALERTS_POLL_INTERVAL = int(os.getenv("ALERTS_POLL_INTERVAL", "10"))  # Інтервал опитування (секунди)

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

# Інтервал перевірки (в годинах) для Facebook
CHECK_INTERVAL_HOURS = int(os.getenv("CHECK_INTERVAL_HOURS", "1"))

# Чи відправляти пости, знайдені при першому запуску
SEND_INITIAL_POSTS = os.getenv("SEND_INITIAL_POSTS", "False").lower() in ("true", "1", "yes")

# Файл збереження вже надісланих постів Facebook
SEEN_POSTS_FILE = os.getenv("SEEN_POSTS_FILE", "seen_posts.json")

# Опціональні Facebook cookies
FB_COOKIES = os.getenv("FB_COOKIES", "")

# Версія браузера для TLS Fingerprint (curl_cffi)
IMPERSONATE_BROWSER = os.getenv("IMPERSONATE_BROWSER", "chrome124")
