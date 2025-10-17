# Инструкция по развертыванию в Portainer

## Проблема
Ошибка при развертывании стека в Portainer, хотя локально все работает корректно.

## Решения

### Вариант 1: Использование специального Dockerfile для Portainer

1. В Portainer выберите "Stacks"
2. Нажмите "Add stack"
3. В поле "Name" введите имя вашего стека (например, safetrade)
4. В поле "Web editor" вставьте содержимое файла `docker-compose.portainer.yml`
5. Убедитесь, что в разделе "Environment" настроены все переменные из `.env` файла
6. Нажмите "Deploy the stack"

### Вариант 2: Использование минимального Dockerfile

Если первый вариант не сработает, попробуйте минимальную версию:

1. Создайте новый stack в Portainer
2. Используйте следующий docker-compose:

```yaml
version: '3.8'

services:
  safetrade:
    build:
      context: .
      dockerfile: Dockerfile.minimal
    image: safetrade:latest
    container_name: safetrade
    restart: unless-stopped
    environment:
      - SAFETRADE_API_KEY=${SAFETRADE_API_KEY}
      - SAFETRADE_API_SECRET=${SAFETRADE_API_SECRET}
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - SUPABASE_URL=${SUPABASE_URL}
      - SUPABASE_KEY=${SUPABASE_KEY}
      - CEREBRAS_API_KEY=${CEREBRAS_API_KEY}
      - ADMIN_CHAT_ID=${ADMIN_CHAT_ID}
    ports:
      - "8443:8443"
    volumes:
      - ./logs:/app/logs
      - ./data:/app/data
```

### Вариант 3: Развертывание с готовым образом

Если сборка образа в Portainer не работает, попробуйте:

1. Собрать образ локально:
   ```bash
   docker build -f Dockerfile.portainer -t safetrade:latest .
   ```

2. Загрузить образ в registry (Docker Hub, GitLab Registry и т.д.)

3. Использовать готовый образ в Portainer:

```yaml
version: '3.8'

services:
  safetrade:
    image: your-registry/safetrade:latest
    container_name: safetrade
    restart: unless-stopped
    environment:
      - SAFETRADE_API_KEY=${SAFETRADE_API_KEY}
      - SAFETRADE_API_SECRET=${SAFETRADE_API_SECRET}
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - SUPABASE_URL=${SUPABASE_URL}
      - SUPABASE_KEY=${SUPABASE_KEY}
      - CEREBRAS_API_KEY=${CEREBRAS_API_KEY}
      - ADMIN_CHAT_ID=${ADMIN_CHAT_ID}
    ports:
      - "8443:8443"
    volumes:
      - ./logs:/app/logs
      - ./data:/app/data
```

### Вариант 4: Отладка в Portainer

1. Включите детальные логи сборки в Portainer:
   - Settings → Advanced settings → Enable debug mode

2. Проверьте логи контейнера после неудачной попытки:
   - Containers → safetrade → Logs

3. Попробуйте выполнить команды из Dockerfile в интерактивном режиме:
   - Создайте контейнер с базовым образом: `docker run -it python:3.11-slim /bin/bash`
   - Выполните команды из Dockerfile пошагово

### Вариант 5: Проверка переменных окружения

Убедитесь, что все переменные окружения правильно настроены в Portainer:

1. В настройках стека перейдите в раздел "Environment"
2. Проверьте наличие всех переменных:
   - SAFETRADE_API_KEY
   - SAFETRADE_API_SECRET
   - TELEGRAM_BOT_TOKEN
   - SUPABASE_URL
   - SUPABASE_KEY
   - CEREBRAS_API_KEY
   - ADMIN_CHAT_ID

### Вариант 6: Использование внешних томов

Если проблема с доступом к локальным файлам, используйте именованные тома:

```yaml
version: '3.8'

services:
  safetrade:
    build:
      context: .
      dockerfile: Dockerfile.minimal
    image: safetrade:latest
    container_name: safetrade
    restart: unless-stopped
    environment:
      - SAFETRADE_API_KEY=${SAFETRADE_API_KEY}
      - SAFETRADE_API_SECRET=${SAFETRADE_API_SECRET}
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
      - SUPABASE_URL=${SUPABASE_URL}
      - SUPABASE_KEY=${SUPABASE_KEY}
      - CEREBRAS_API_KEY=${CEREBRAS_API_KEY}
      - ADMIN_CHAT_ID=${ADMIN_CHAT_ID}
    ports:
      - "8443:8443"
    volumes:
      - safetrade_logs:/app/logs
      - safetrade_data:/app/data

volumes:
  safetrade_logs:
  safetrade_data:
```

## Частые проблемы и решения

1. **Ошибка сети при apt-get update**:
   - Используйте Dockerfile.minimal (только gcc)
   - Добавьте `|| true` после apt-get update

2. **Проблемы с кэшем**:
   - Очистите кэш Docker в Portainer: Settings → Cleanup

3. **Несовместимость платформы**:
   - Укажите платформу в docker-compose:
     ```yaml
     platform: linux/amd64
     ```

4. **Проблемы с правами доступа**:
   - Добавьте в docker-compose:
     ```yaml
     user: "1000:1000"
     ```

## Проверка работоспособности

После успешного развертывания:

1. Проверьте логи контейнера в Portainer
2. Убедитесь, что бот отвечает на команды
3. Проверьте доступность webhook (если используется)

Если ни один из вариантов не помог, предоставьте логи ошибки из Portainer для дальнейшей диагностики.