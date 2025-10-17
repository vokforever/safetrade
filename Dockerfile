# Используем официальный образ Python
FROM python:3.11-slim-bullseye

# Устанавливаем переменные окружения
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Устанавливаем системные зависимости, создаем виртуальную группу для сборки
RUN apt-get update && \
    apt-get install -y --no-install-recommends curl && \
    apt-get install -y --no-install-recommends --virtual .build-deps gcc && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Копируем зависимости и устанавливаем их
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt && \
    apt-get purge -y --auto-remove .build-deps

# Создаем пользователя и директории
RUN useradd --create-home --shell /bin/bash appuser && \
    mkdir -p /app/logs /app/data && \
    chown -R appuser:appuser /app

# Копируем код приложения и выставляем права
COPY --chown=appuser:appuser . .

# Переключаемся на непривилегированного пользователя
USER appuser

# Открываем порт для webhook
EXPOSE 8443

# Добавляем проверку состояния
HEALTHCHECK --interval=5m --timeout=30s --start-period=1m --retries=3 \
  CMD curl -f https://api.telegram.org || exit 1

# Команда для запуска
CMD ["python", "main.py"]