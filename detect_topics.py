import sys
import time
import requests
from dotenv import set_key, load_dotenv

if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

load_dotenv()
from config import TELEGRAM_BOT_TOKEN


def main():
    if not TELEGRAM_BOT_TOKEN:
        print("❌ Спочатку вкажіть TELEGRAM_BOT_TOKEN у файлі .env!")
        sys.exit(1)

    print("=" * 65)
    print("🤖 ДЕТЕКТОР ВЕТОК (TOPICS) ДЛЯ '12312312 Chat'")
    print("=" * 65)
    print("1. Додайте вашого бота в групу '12312312 Chat' як Адміністратора.")
    print("2. Напишіть повідомлення '1' або 'фейсбук 1' у першу гілку.")
    print("3. Напишіть повідомлення '2' або 'фейсбук 2' у другу гілку.")
    print("4. Напишіть повідомлення '3' або 'тривога' у гілку тривог.")
    print("=" * 65)
    print("Очікую повідомлення з гілок... (Натисніть Ctrl+C для виходу)\n")

    offset = 0
    found_topics = {}
    target_chat_id = None

    while True:
        try:
            url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/getUpdates?offset={offset}&timeout=10"
            res = requests.get(url, timeout=15).json()

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
                    elif "чигур" in ident or "фейсбук 3" in ident or "fb3" in ident or "3" in ident and "тривог" not in ident:
                        assigned = "THREAD_ID_FB_3"
                    elif "одес" in ident and ("тривог" in ident or "тревог" in ident or "радар" in ident):
                        assigned = "THREAD_ID_ALERTS_ODESA"
                    elif "тривог" in ident or "тревог" in ident or "радар" in ident:
                        assigned = "THREAD_ID_ALERTS"

                    if assigned:
                        found_topics[assigned] = thread_id
                        print(f"   ✅ Прив'язано до: {assigned} = {thread_id}\n")
                    else:
                        print(f"   ℹ️ Thread ID = {thread_id} (вкажіть потрібну змінну в .env вручну)\n")

                    # Автоматично оновлюємо .env
                    set_key(".env", "TELEGRAM_CHAT_ID", str(chat_id))
                    for k, v in found_topics.items():
                        set_key(".env", k, str(v))

                    if len(found_topics) == 3:
                        print("🎉 ВСІ 3 ВЕТКИ УСПІШНО ВИЯВЛЕНО ТА ЗБЕРЕЖЕНО В .env:")
                        for k, v in found_topics.items():
                            print(f"   {k} = {v}")
                        print(f"   TELEGRAM_CHAT_ID = {target_chat_id}")
                        print("\nНалаштування завершено! Можна запускати main.py та eradar_sarny.py")
                        return

            time.sleep(1)
        except KeyboardInterrupt:
            print("\nЗупинено користувачем.")
            break
        except Exception:
            time.sleep(2)


if __name__ == "__main__":
    main()
