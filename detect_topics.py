# -*- coding: utf-8 -*-
import os
import sys
import time
import json

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


def load_env_fallback(filepath=".env"):
    """Завантажує змінні з .env без зовнішніх бібліотек."""
    if not os.path.exists(filepath):
        return
    try:
        from dotenv import load_dotenv
        load_dotenv(filepath)
    except ImportError:
        with open(filepath, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                k = k.strip()
                v = v.strip().strip("'\"")
                if k not in os.environ:
                    os.environ[k] = v


def set_env_key(filepath=".env", key="", value=""):
    """Оновлює або додає ключ у .env (працює навіть без python-dotenv)."""
    try:
        from dotenv import set_key
        set_key(filepath, key, str(value))
        return
    except ImportError:
        pass

    lines = []
    if os.path.exists(filepath):
        with open(filepath, "r", encoding="utf-8") as f:
            lines = f.readlines()

    found = False
    new_lines = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith(f"{key}=") or stripped == key:
            new_lines.append(f"{key}={value}\n")
            found = True
        else:
            new_lines.append(line)

    if not found:
        new_lines.append(f"{key}={value}\n")

    with open(filepath, "w", encoding="utf-8") as f:
        f.writelines(new_lines)


def fetch_json(url, timeout=15):
    """Отримує JSON з URL через requests або urllib."""
    try:
        import requests
        return requests.get(url, timeout=timeout).json()
    except ImportError:
        import urllib.request
        req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))


# Завантажуємо налаштування перед імпортом config
load_env_fallback(".env")
from config import TELEGRAM_BOT_TOKEN


def main():
    token = TELEGRAM_BOT_TOKEN or os.getenv("TELEGRAM_BOT_TOKEN", "")
    if not token:
        print("❌ Спочатку вкажіть TELEGRAM_BOT_TOKEN у файлі .env!")
        sys.exit(1)

    print("=" * 65)
    print("🤖 ДЕТЕКТОР ВЕТОК (TOPICS) ДЛЯ TELEGRAM ГРУПИ")
    print("=" * 65)
    print("1. Додайте вашого бота в групу як Адміністратора.")
    print("2. Напишіть повідомлення у кожну гілку, яку хочете визначити:")
    print("   • '1' або 'фейсбук 1'  -> THREAD_ID_FB_1")
    print("   • '2' або 'фейсбук 2'  -> THREAD_ID_FB_2")
    print("   • '3' або 'фейсбук 3'  -> THREAD_ID_FB_3")
    print("   • 'тривога' або 'сарни' -> THREAD_ID_ALERTS")
    print("   • 'світло' або 'дтек'   -> THREAD_ID_POWER")
    print("   • 'одеса'              -> THREAD_ID_ALERTS_ODESA")
    print("   (або будь-який текст — скрипт покаже точний Thread ID кожної гілки)")
    print("=" * 65)
    print("Очікую повідомлення з гілок... (Натисніть Ctrl+C для виходу)\n")

    offset = 0
    found_topics = {}
    target_chat_id = None

    while True:
        try:
            url = f"https://api.telegram.org/bot{token}/getUpdates?offset={offset}&timeout=10"
            res = fetch_json(url, timeout=15)

            for item in res.get("result", []):
                offset = item["update_id"] + 1
                msg = item.get("message") or item.get("channel_post")
                if not msg:
                    continue

                chat = msg.get("chat", {})
                chat_id = chat.get("id")
                chat_title = chat.get("title", "Чат")
                thread_id = msg.get("message_thread_id")
                text = msg.get("text", "")

                topic_created = msg.get("forum_topic_created")
                topic_name = topic_created.get("name") if topic_created else None

                if thread_id:
                    target_chat_id = chat_id
                    print(f"👉 Отримано повідомлення в групі '{chat_title}' (ID: {chat_id})")
                    print(f"   Ветка (Thread ID): {thread_id} | Текст: '{text}'")

                    ident = (text + " " + (topic_name or "")).lower()
                    assigned = None

                    if "1" in ident or "фейсбук 1" in ident or "fb1" in ident or "сарн фб" in ident:
                        assigned = "THREAD_ID_FB_1"
                    elif "2" in ident or "фейсбук 2" in ident or "fb2" in ident or "поліц" in ident:
                        assigned = "THREAD_ID_FB_2"
                    elif "світл" in ident or "свет" in ident or "відключ" in ident or "отключ" in ident or "дтек" in ident or "обленерг" in ident or "power" in ident:
                        assigned = "THREAD_ID_POWER"
                    elif "тривог" in ident or "тревог" in ident or "радар" in ident or "сарн" in ident:
                        assigned = "THREAD_ID_ALERTS"

                    if assigned:
                        found_topics[assigned] = thread_id
                        print(f"   ✅ Прив'язано до: {assigned} = {thread_id}\n")
                    else:
                        print(f"   ℹ️ Thread ID = {thread_id} (вкажіть потрібну змінну в .env вручну)\n")

                    # Автоматично оновлюємо .env
                    set_env_key(".env", "TELEGRAM_CHAT_ID", str(chat_id))
                    for k, v in found_topics.items():
                        set_env_key(".env", k, str(v))

                    print("📊 Знайдені наразі змінні у .env:")
                    for k, v in found_topics.items():
                        print(f"   {k} = {v}")
                    print(f"   TELEGRAM_CHAT_ID = {target_chat_id}")
                    print("-" * 65)

            time.sleep(1)
        except KeyboardInterrupt:
            print("\nЗупинено користувачем.")
            break
        except Exception as e:
            time.sleep(2)


if __name__ == "__main__":
    main()
