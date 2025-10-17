# Используем официальный образ Python
FROM python:3.11-slim-bullseye

# Устанавливаем переменные окружения
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Копируем только requirements.txt и сразу устанавливаем зависимости.
# Мы пропускаем шаг с apt-get, который вызывает ошибку.
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Создаем пользователя и директории
RUN useradd --create-home --shell /bin/bash appuser && \
    mkdir -p /app/data && \
    chown -R appuser:appuser /app

# Копируем код приложения и выставляем права
COPY --chown=appuser:appuser . .

# Переключаемся на непривилегированного пользователя
USER appuser

# Открываем порт для webhook
EXPOSE 8443

# HEALTHCHECK временно удален, так как мы не устанавливаем curl

# Команда для запуска
CMD ["python", "main.py"]