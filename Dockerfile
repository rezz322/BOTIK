FROM python:3.11-slim

# Встановлення необхідних утиліт
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

# Встановлення часового поясу (Київ)
ENV TZ=Europe/Kyiv
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Встановлення залежностей Python
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Копіювання файлів проєкту
COPY . .

# Робимо стартовий скрипт виконуваним
RUN chmod +x start.sh

CMD ["./start.sh"]
