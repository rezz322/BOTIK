import sys
import time
import signal
import subprocess
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("Runner")


def main():
    logger.info("🚀 Запуск Facebook та UkraineAlarm ботів...")

    # Запускаємо UkraineAlarm моніторинг
    proc_radar = subprocess.Popen(
        [sys.executable, "-u", "eradar_sarny.py"],
        stdout=sys.stdout,
        stderr=sys.stderr,
    )

    # Запускаємо Facebook чекер
    proc_fb = subprocess.Popen(
        [sys.executable, "-u", "main.py"],
        stdout=sys.stdout,
        stderr=sys.stderr,
    )

    def shutdown(signum, frame):
        logger.info("🛑 Отримано сигнал зупинки, завершення процесів...")
        for p in (proc_radar, proc_fb):
            try:
                p.terminate()
            except Exception:
                pass
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Очікуємо роботу процесів
    while True:
        if proc_radar.poll() is not None:
            logger.error(f"⚠️ Процес UkraineAlarm несподівано завершився з кодом {proc_radar.returncode}!")
            proc_fb.terminate()
            break
        if proc_fb.poll() is not None:
            logger.error(f"⚠️ Процес Facebook несподівано завершився з кодом {proc_fb.returncode}!")
            proc_radar.terminate()
            break
        time.sleep(2)


if __name__ == "__main__":
    main()
