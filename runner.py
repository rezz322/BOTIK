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
    logger.info("🚀 Запуск Facebook, UkraineAlarm та Рівнеобленерго (Сарни) ботів...")

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

    # Запускаємо моніторинг відключень світла (Рівнеобленерго / Сарни)
    proc_power = subprocess.Popen(
        [sys.executable, "-u", "epower_sarny.py"],
        stdout=sys.stdout,
        stderr=sys.stderr,
    )

    procs = [proc_radar, proc_fb, proc_power]

    def shutdown(signum, frame):
        logger.info("🛑 Отримано сигнал зупинки, завершення процесів...")
        for p in procs:
            try:
                p.terminate()
            except Exception:
                pass
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    # Очікуємо роботу процесів та перезапускаємо при збоях
    while True:
        if proc_radar.poll() is not None:
            logger.error(f"⚠️ Процес UkraineAlarm завершився з кодом {proc_radar.returncode}! Перезапуск через 5 сек...")
            time.sleep(5)
            proc_radar = subprocess.Popen(
                [sys.executable, "-u", "eradar_sarny.py"],
                stdout=sys.stdout,
                stderr=sys.stderr,
            )
            procs[0] = proc_radar

        if proc_fb.poll() is not None:
            logger.error(f"⚠️ Процес Facebook завершився з кодом {proc_fb.returncode}! Перезапуск через 5 сек...")
            time.sleep(5)
            proc_fb = subprocess.Popen(
                [sys.executable, "-u", "main.py"],
                stdout=sys.stdout,
                stderr=sys.stderr,
            )
            procs[1] = proc_fb

        if proc_power.poll() is not None:
            logger.error(f"⚠️ Процес моніторингу відключень завершився з кодом {proc_power.returncode}! Перезапуск через 5 сек...")
            time.sleep(5)
            proc_power = subprocess.Popen(
                [sys.executable, "-u", "epower_sarny.py"],
                stdout=sys.stdout,
                stderr=sys.stderr,
            )
            procs[2] = proc_power

        time.sleep(3)


if __name__ == "__main__":
    main()
