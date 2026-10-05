import sys
import time
import logging
from apscheduler.schedulers.blocking import BlockingScheduler

# Налаштовуємо вивід консолі у UTF-8
if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from config import (
    TARGET_URLS,
    CHECK_INTERVAL_HOURS,
    SEND_INITIAL_POSTS,
    TELEGRAM_BOT_TOKEN,
    TELEGRAM_CHAT_ID,
    URL_TO_THREAD,
    THREAD_ID_FB_1,
    THREAD_ID_FB_2,
    IMPERSONATE_BROWSER,
)
from facebook import FacebookParser, Storage
from telegram_sender import TelegramSender

# Логування
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
        logging.FileHandler("bot.log", encoding="utf-8"),
    ],
)
logger = logging.getLogger("AutoFBTelegramBot")


class AutoBot:
    def __init__(self):
        self.storage = Storage()
        self.parser = FacebookParser(browser_fingerprint=IMPERSONATE_BROWSER)
        self.sender = TelegramSender(token=TELEGRAM_BOT_TOKEN, channel=TELEGRAM_CHAT_ID)

    def job_check_profiles(self):
        """
        Щогодинна перевірка:
        Отримує останній пост для кожної сторінки та відправляє у відповідну гілку (ветку).
        """
        logger.info("=" * 60)
        logger.info("🔄 Запуск циклу перевірки останніх Facebook постів...")

        for idx, url in enumerate(TARGET_URLS):
            try:
                # Визначаємо гілку (ветку) для цього посилання
                target_thread = URL_TO_THREAD.get(url) or (THREAD_ID_FB_1 if idx == 0 else THREAD_ID_FB_2)

                # Отримуємо виключно найостанніший пост
                latest_post = self.parser.fetch_latest_post(url)
                if not latest_post:
                    logger.warning(f"⚠️ Не вдалося отримати публікації для: {url}")
                    continue

                current_post_id = str(latest_post["post_id"])
                previous_post_id = self.storage.get_last_post_id(url)

                logger.info(f"🔎 Перевірка посилання: {url}")
                logger.info(f"   Цільова ветка (thread_id): {target_thread}")
                logger.info(f"   Поточний ID: {current_post_id} | Минулий збережений ID: {previous_post_id}")

                if previous_post_id is None:
                    # Перша ініціалізація
                    if SEND_INITIAL_POSTS:
                        logger.info(f"📢 Перший запуск: відправляємо пост (ID: {current_post_id}) у ветку {target_thread}")
                        self.sender.send_post(latest_post, thread_id=target_thread)
                    else:
                        logger.info(f"ℹ️ Перший запуск: зберігаємо ID {current_post_id} як минулий без відправки.")

                    self.storage.set_last_post_id(url, current_post_id)

                elif current_post_id != previous_post_id:
                    # ID змінився -> публікуємо новий пост у його ветку
                    logger.info(f"🆕 ЗНАЙДЕНО НОВИЙ ПОСТ! ID: {current_post_id} (минулий: {previous_post_id})")
                    logger.info(f"📢 Відправляємо у ветку {target_thread}...")

                    success = self.sender.send_post(latest_post, thread_id=target_thread)
                    if success or not TELEGRAM_BOT_TOKEN:
                        self.storage.set_last_post_id(url, current_post_id)
                        logger.info(f"💾 ID {current_post_id} збережено як минулий.")

                else:
                    logger.info(f"⏸ Пост не змінився (ID {current_post_id} == минулий ID). Пропускаємо.")

                # Пауза між запитами
                time.sleep(3)

            except Exception as e:
                logger.error(f"Помилка при обробці {url}: {e}", exc_info=True)

        logger.info(f"🏁 Перевірку завершено. Наступна перевірка рівно через {CHECK_INTERVAL_HOURS} год.")
        logger.info("=" * 60)

    def run(self):
        logger.info("🤖 Facebook to Telegram Auto Request Bot запущено!")
        logger.info(f"📌 Чат призначення: {TELEGRAM_CHAT_ID}")
        logger.info(f"📌 Ветка Фейсбук 1: {THREAD_ID_FB_1}")
        logger.info(f"📌 Ветка Фейсбук 2: {THREAD_ID_FB_2}")
        logger.info(f"⏱ Інтервал перевірки: кожні {CHECK_INTERVAL_HOURS} год.")

        if not TELEGRAM_BOT_TOKEN:
            logger.warning("⚠️ УВАГА: TELEGRAM_BOT_TOKEN не задано в .env файлі!")

        # Перший запуск одразу
        self.job_check_profiles()

        # Планувальник щогодини
        scheduler = BlockingScheduler()
        scheduler.add_job(
            self.job_check_profiles,
            "interval",
            hours=CHECK_INTERVAL_HOURS,
            id="fb_checker_job",
            replace_existing=True,
        )

        try:
            scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("🛑 Бот зупинений.")


if __name__ == "__main__":
    bot = AutoBot()
    bot.run()
