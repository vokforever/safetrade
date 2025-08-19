Вот расширенная документация для работы с API SafeTrade, основанная на файле кода вашего бота и репозитории примера клиента с GitHub:

***

# Документация по API SafeTrade и работе с примером клиента

## Общие сведения

API SafeTrade предоставляет REST и WebSocket интерфейсы для взаимодействия с криптовалютной биржей SafeTrade. Основной функционал включает:

- Авторизацию запросов по HMAC-SHA256
- Получение списка торговых пар
- Получение балансов на счёте
- Получение рыночных данных (цены, ордербук)
- Создание, отслеживание и отмену ордеров на торговлю
- Использование WebSocket для получения данных в реальном времени

***

## Аутентификация

Все защищённые API запросы требуют передачи заголовков с API ключом, nonce и подписанным HMAC:

- `X-Auth-Apikey`: ваш API ключ
- `X-Auth-Nonce`: метка времени в миллисекундах
- `X-Auth-Signature`: HMAC-SHA256 подпись строки `nonce + key` с секретом

Функция генерации подписи:

```python
def generate_signature(nonce, key, secret_bytes):
    string_to_sign = nonce + key
    return hmac.new(secret_bytes, string_to_sign.encode('utf-8'), hashlib.sha256).hexdigest()
```

Заголовки запроса:

```python
def get_auth_headers():
    nonce = str(int(time.time() * 1000))
    signature = generate_signature(nonce, API_KEY, API_SECRET_BYTES)
    return {
        'X-Auth-Apikey': API_KEY,
        'X-Auth-Nonce': nonce,
        'X-Auth-Signature': signature,
        'Content-Type': 'application/json'
    }
```

***

## Основные REST API методы

### Получение всех торговых пар

- Endpoint: `GET /public/markets`
- Возвращает список всех торговых пар.
- Пример фильтрации: пары с `quote_unit` равным `usdt` исключая некоторые валюты.

```python
def get_all_markets():
    # Получаем список торговых пар через запрос
    # Кэширование и ошибки обработки включены
```

### Получение балансов пользователя

- Endpoint: `GET /trade/account/balances/spot`
- Возвращает список балансов всех валют пользователя.
- Фильтруются исключённые валюты и влияющие на торговлю.

```python
def get_sellable_balances():
    # Возвращает балансы на аккаунте с фильтрацией
```

### Получение текущих котировок

- Endpoint: `GET /public/markets/{symbol}/tickers`
- Возвращает последнюю цену и торговый объём для торговой пары.

```python
def get_ticker_price(symbol):
    # Получает цену и кеширует результат
```

### Получение книги ордеров

- Endpoint: `GET /public/markets/{symbol}/order-book`
- Возвращает данные книги ордеров (bids и asks).

```python
def get_orderbook(symbol):
    # Получение книги ордеров с кешированием
```

***

## Торговые операции

### Создание ордера на продажу

- Endpoint: `POST /trade/market/orders`
- Параметры:
  - `market` — торговая пара (например, btcusdt)
  - `side` — стратегия `sell`
  - `type` — сумма вида `market` или `limit`
  - `amount` — количество для продажи
  - `price` — для limit ордеров

```python
def create_sell_order_safetrade(market_symbol, amount, order_type="market", price=None):
    # Создаёт ордер, валидирует параметры,
    # сохраняет в локальную базу
```

### Отслеживание исполнения ордера

- Endpoint: `GET /trade/market/orders/{order_id}/trades`
- Возвращает список сделок по ордеру.

```python
def track_order_execution(order_id, timeout=300):
    # Проверяет статус и кол-во исполненных сделок
```

### Отмена ордера

- Endpoint: `POST /trade/market/orders/{order_id}/cancel`
- Отменяет ордер по ID.

```python
def cancel_order(order_id):
    # Отправляет запрос на отмену и обновляет локальный статус
```

***

## WebSocket клиент (из репозитория)

- Пример реализации клиента WebSocket на Python для SafeTrade.
- Позволяет подписываться на каналы с данными в реальном времени.
- Требует Python 3.7+, установка зависимостей из `requirements.txt`.

**Основные шаги по работе с клиентом**:

1. Клонировать репозиторий:

```
git clone https://github.com/safetrade-exchange/example-client.git
cd example-client
```

2. Установить зависимости:

```
pip install -r requirements.txt
```

3. В файле `main.py` заменить значения:

```python
yourAPIkey = ""
yourAPISecret = ""
```

4. Запустить клиент:

```
python main.py
```

***

## Дополнительные функции в боте

- Приоритизация валют для продажи с учётом стоимости, ликвидности, волатильности и spread.
- Автоматический выбор торговой стратегии с помощью ИИ (Cerebras).
- Поддержка разных стратегий продажи: market, limit, twap, iceberg, adaptive.
- Кэширование данных рынков, цен и книги ордеров для оптимизации запросов.
- Планировщик автоматических продаж с ограничением одновременных ордеров.
- Логирование операций и ошибок.
- Валидация параметров ордеров и рыночных условий.

***

Если вам нужна помощь с конкретными API вызовами или примерами работы с WebSocket клиентом из репозитория — могу помочь с кодом и разъяснениями.

[1] https://ppl-ai-file-upload.s3.amazonaws.com/web/direct-files/attachments/39141579/0b7329bd-bdf3-419c-8dc3-f23e446cd59e/paste.txt
[2] https://github.com/safetrade-exchange/example-client