# SafeTrade Docker Compose Setup

This Docker Compose setup includes all services needed to run the SafeTrade bot with a local Supabase-compatible database.

## Services Included

1. **safetrade-bot** - The main SafeTrade bot application
2. **supabase-db** - PostgreSQL database with Supabase schema
3. **supabase-studio** - Web UI for database management (optional)

## Prerequisites

- Docker installed on your system
- Docker Compose installed on your system

## Setup Instructions

1. **Create Environment File**
   Copy the example environment file and fill in your values:
   ```bash
   cp env_example.txt .env
   ```
   Then edit `.env` with your actual API keys and credentials.

2. **Update Environment Variables**
   In your `.env` file, make sure to set at least these required variables:
   ```
   SAFETRADE_API_KEY=your_safetrade_api_key_here
   SAFETRADE_API_SECRET=your_safetrade_api_secret_here
   SUPABASE_URL=http://supabase-db:5432
   SUPABASE_KEY=your_supabase_anon_key_here
   ```

3. **Start Services**
   ```bash
   docker-compose up -d
   ```

4. **View Logs**
   ```bash
   docker-compose logs -f safetrade-bot
   ```

5. **Access Supabase Studio** (Optional)
   Open your browser and go to: http://localhost:3000

## Configuration

### Volume Mounts
- `./logs` - Bot logs are stored here
- `./data` - Local data storage
- `supabase_data` - Database persistence

### Network
All services are on the `safetrade-network` bridge network.

## Useful Commands

- **Start services**: `docker-compose up -d`
- **Stop services**: `docker-compose down`
- **View logs**: `docker-compose logs -f`
- **Restart bot only**: `docker-compose restart safetrade-bot`
- **Check service status**: `docker-compose ps`

## Security Notes

1. Change the default PostgreSQL password in `docker-compose.yml` for production use
2. Ensure your `.env` file is not committed to version control
3. The Supabase Studio is exposed on port 3000 - restrict access in production

## Troubleshooting

1. **Database Connection Issues**
   - Check that all services are running: `docker-compose ps`
   - Verify environment variables in `.env`
   - Check database logs: `docker-compose logs supabase-db`

2. **Bot Not Starting**
   - Check bot logs: `docker-compose logs safetrade-bot`
   - Verify all required environment variables are set

3. **Supabase Studio Not Accessible**
   - Ensure port 3000 is not blocked by firewall
   - Check Studio logs: `docker-compose logs supabase-studio`

---

# Настройка Docker Compose для SafeTrade

Эта настройка Docker Compose включает все сервисы, необходимые для запуска бота SafeTrade с локальной базой данных, совместимой с Supabase.

## Включенные сервисы

1. **safetrade-bot** - Основное приложение бота SafeTrade
2. **supabase-db** - База данных PostgreSQL со схемой Supabase
3. **supabase-studio** - Веб-интерфейс для управления базой данных (опционально)

## Предварительные требования

- Установленный Docker на вашей системе
- Установленный Docker Compose на вашей системе

## Инструкции по настройке

1. **Создание файла окружения**
   Скопируйте пример файла окружения и заполните своими значениями:
   ```bash
   cp env_example.txt .env
   ```
   Затем отредактируйте `.env` с вашими реальными ключами API и учетными данными.

2. **Обновление переменных окружения**
   В вашем файле `.env` убедитесь, что установлены как минимум эти обязательные переменные:
   ```
   SAFETRADE_API_KEY=your_safetrade_api_key_here
   SAFETRADE_API_SECRET=your_safetrade_api_secret_here
   SUPABASE_URL=http://supabase-db:5432
   SUPABASE_KEY=your_supabase_anon_key_here
   ```

3. **Запуск сервисов**
   ```bash
   docker-compose up -d
   ```

4. **Просмотр логов**
   ```bash
   docker-compose logs -f safetrade-bot
   ```

5. **Доступ к Supabase Studio** (Опционально)
   Откройте браузер и перейдите по адресу: http://localhost:3000

## Конфигурация

### Монтирование томов
- `./logs` - Логи бота хранятся здесь
- `./data` - Локальное хранилище данных
- `supabase_data` - Постоянное хранение базы данных

### Сеть
Все сервисы находятся в сети `safetrade-network` (bridge).

## Полезные команды

- **Запуск сервисов**: `docker-compose up -d`
- **Остановка сервисов**: `docker-compose down`
- **Просмотр логов**: `docker-compose logs -f`
- **Перезапуск только бота**: `docker-compose restart safetrade-bot`
- **Проверка статуса сервисов**: `docker-compose ps`

## Замечания по безопасности

1. Измените пароль PostgreSQL по умолчанию в `docker-compose.yml` для использования в production
2. Убедитесь, что ваш файл `.env` не попадает в систему контроля версий
3. Supabase Studio доступен через порт 3000 - ограничьте доступ в production

## Устранение неполадок

1. **Проблемы с подключением к базе данных**
   - Проверьте, что все сервисы запущены: `docker-compose ps`
   - Проверьте переменные окружения в `.env`
   - Проверьте логи базы данных: `docker-compose logs supabase-db`

2. **Бот не запускается**
   - Проверьте логи бота: `docker-compose logs safetrade-bot`
   - Убедитесь, что все обязательные переменные окружения установлены

3. **Supabase Studio недоступен**
   - Убедитесь, что порт 3000 не заблокирован фаерволом
   - Проверьте логи Studio: `docker-compose logs supabase-studio`