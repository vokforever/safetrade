# Используем официальный образ Python как базовый
FROM python:3.11-slim-buster

# Устанавливаем рабочую директорию внутри контейнера
WORKDIR /app

# Устанавливаем зависимости для работы с PostgreSQL
RUN apt-get update && apt-get install -y \
    gcc \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Копируем файл requirements.txt в рабочую директорию контейнера
COPY requirements.txt .

# Устанавливаем все зависимости, указанные в requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Копируем весь остальной код вашего бота в рабочую директорию контейнера
COPY . .

# Создаем директории для логов и данных
RUN mkdir -p /app/logs /app/data

# Эти переменные окружения здесь указаны с "dummy" значениями.
# Реальные значения должны быть настроены в .env файле или docker-compose.yml
ENV SAFETRADE_API_KEY="dummy" \
    SAFETRADE_API_SECRET="dummy" \
    TELEGRAM_BOT_TOKEN="dummy" \
    SUPABASE_URL="dummy" \
    SUPABASE_KEY="dummy" \
    CEREBRAS_API_KEY="dummy" \
    ADMIN_CHAT_ID="dummy"

# Открываем порт для webhook (если используется)
EXPOSE 8443

# Команда для запуска приложения при старте контейнера
CMD ["python", "main.py"]