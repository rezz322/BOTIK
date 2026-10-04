#!/bin/sh
echo "🚀 Запуск Facebook та eRadar ботів у Docker..."

# Запуск eRadar моніторингу у фоні
python -u eradar_sarny.py &

# Запуск Facebook чекера у головному процесі
exec python -u main.py
