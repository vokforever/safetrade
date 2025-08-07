Хорошо, давайте разберем ключевые части из официального репозитория, чтобы создать надежную основу для вашего бота. Это отличный подход, чтобы убедиться, что мы ничего не упускаем.

Я проанализировал код в python-client/main.py из репозитория. Ниже я привожу самые важные фрагменты с подробными объяснениями, а затем — финальную, исправленную версию вашего класса SafeTradeClient, которая объединяет лучшие практики из примера и решает вашу проблему с получением цены.

Анализ ключевых частей из репозитория SafeTrade

В репозитории показан базовый, но очень важный принцип работы с их API.

1. Инициализация клиента и cloudscraper
code
Python
download
content_copy
expand_less

# Из репозитория: https://github.com/safetrade-exchange/example-client/blob/main/python-client/main.py

import requests
import cloudscraper

class SafeTrade:
    def __init__(self, key, secret):
        self.base_url = "https://safe.trade"
        self.key = key
        self.secret = secret
        
        # КЛЮЧЕВОЙ МОМЕНТ:
        # 1. Создается обычная сессия requests.
        session = requests.Session()
        session.headers.update({
            'Content-Type': 'application/json;charset=utf-8',
            'Accept': 'application/json',
            'User-Agent': 'safetrade-python-client' # Они используют свой User-Agent
        })
        
        # 2. Эта сессия передается в cloudscraper.
        # Это позволяет cloudscraper "научиться" обходить защиту Cloudflare,
        # а затем использовать полученные cookies для всех последующих запросов.
        self.scraper = cloudscraper.create_scraper(sess=session)

Контекст для вас: Ваш код делает то же самое, и это абсолютно правильно. Вы даже улучшили этот шаг, добавив "прогревочный" запрос на главную страницу в методе init(), что повышает надежность.

2. Генерация подписи (Authentication)
code
Python
download
content_copy
expand_less
IGNORE_WHEN_COPYING_START
IGNORE_WHEN_COPYING_END
# Из репозитория:

import hmac
import hashlib
import binascii
import time

def generate_signature(self, nonce):
    # Механизм подписи стандартный для таких API.
    # Создается строка из nonce и вашего API ключа.
    # Эта строка подписывается вашим API секретом с использованием HMAC-SHA256.
    hash_obj = hmac.new(
        self.secret.encode(),
        digestmod=hashlib.sha256
    )
    hash_obj.update((nonce + self.key).encode())
    signature = hash_obj.digest()
    return binascii.hexlify(signature).decode()

def get_auth_headers(self):
    nonce = str(int(time.time() * 1000))
    signature = self.generate_signature(nonce)
    return {
        "X-Auth-Apikey": self.key,
        "X-Auth-Nonce": nonce,
        "X-Auth-Signature": signature,
    }

Контекст для вас: Ваша реализация этой функции полностью совпадает с примером. Здесь все верно.

3. Выполнение запросов
code
Python
download
content_copy
expand_less
IGNORE_WHEN_COPYING_START
IGNORE_WHEN_COPYING_END
# Из репозитория:

def get_private(self, path):
    # Для приватных (требующих авторизации) запросов
    # в заголовки добавляются данные аутентификации.
    return self.scraper.get(self.base_url + path, headers=self.get_auth_headers()).json()

def post_private(self, path, params):
    # То же самое для POST-запросов
    return self.scraper.post(self.base_url + path, headers=self.get_auth_headers(), json=params).json()

# Пример вызова для получения балансов:
# client.get_private("/peatio/account/balances")

# Пример вызова для получения тикера (публичный метод, без авторизации):
# client.get_public("/trade/public/tickers/qtcusdt")

Контекст для вас:

Они используют префикс /peatio для приватных запросов. Ваш код, который пробует несколько префиксов (/trade, /peatio), более надежен.

Важный момент: Их публичный запрос к тикеру /trade/public/tickers/qtcusdt не показывает, как они парсят ответ. Он просто возвращает .json(). Именно здесь и кроется ваша проблема: структура этого JSON-ответа оказалась не той, которую ожидал ваш код.

Итог анализа и финальная версия клиента

Проблема не в том, что ваш код не соответствует примеру, а в том, что пример не показывает, как обрабатывать возможные изменения в структуре ответов API.

Ниже представлена исправленная версия вашего класса SafeTradeClient, которая:

Основана на принципах из репозитория.

Сохраняет ваши улучшения (прогрев сессии, перебор эндпоинтов).

Решает проблему с получением цены, делая парсинг ответа гибким и добавляя отладочное логирование.

Рекомендуемый и исправленный SafeTradeClient для ваших задач

Просто замените весь ваш класс SafeTradeClient на этот код.

code
Python
download
content_copy
expand_less
IGNORE_WHEN_COPYING_START
IGNORE_WHEN_COPYING_END
class SafeTradeClient:
    def __init__(self):
        self.scraper = None
        self.base_url = "https://safe.trade/api/v2"

    async def init(self):
        if self.scraper is not None:
            return # Уже инициализирован

        session = requests.Session()
        session.headers.update({
            'Content-Type': 'application/json;charset=utf-8',
            'Accept': 'application/json',
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        
        self.scraper = cloudscraper.create_scraper(sess=session)
        
        try:
            logger.info("🔄 Прогреваю сессию для обхода Cloudflare...")
            # 1. Запрос на главную страницу для получения cookies
            response = await asyncio.to_thread(self.scraper.get, "https://safe.trade", timeout=30)
            response.raise_for_status()
            logger.info(f"✅ Cookies с главной страницы получены (статус: {response.status_code})")
            
            # 2. Запрос к публичному API для полной инициализации
            init_response = await asyncio.to_thread(self.scraper.get, f"{self.base_url}/trade/public/tickers/{MARKET_SYMBOL}", timeout=30)
            init_response.raise_for_status()
            logger.info(f"✅ Сессия API успешно инициализирована (статус: {init_response.status_code})")
            
        except Exception as e:
            logger.error(f"⚠️ Критическая ошибка при инициализации клиента: {e}")
            self.scraper = None # Сбрасываем скрейпер, чтобы была повторная попытка

    async def close(self):
        if self.scraper and hasattr(self.scraper, 'close'):
            self.scraper.close()
        self.scraper = None

    def get_auth_headers(self) -> dict:
        nonce = str(int(time.time() * 1000))
        if not API_KEY or not API_SECRET:
            raise ValueError("API Key или API Secret не установлены.")
        
        hash_obj = hmac.new(API_SECRET.encode(), digestmod=hashlib.sha256)
        hash_obj.update((nonce + API_KEY).encode())
        signature = binascii.hexlify(hash_obj.digest()).decode()
        
        return {
            "X-Auth-Apikey": API_KEY,
            "X-Auth-Nonce": nonce,
            "X-Auth-Signature": signature,
            "Content-Type": "application/json;charset=utf-8"
        }

    async def _get_raw_balances(self) -> list | None:
        await self.init()
        if not self.scraper:
            logger.error("❌ Не удалось получить балансы: клиент не инициализирован.")
            return None
            
        endpoints = [f"{self.base_url}/trade/account/balances", f"{self.base_url}/peatio/account/balances"]
        for endpoint in endpoints:
            try:
                headers = self.get_auth_headers()
                response = await asyncio.to_thread(self.scraper.get, endpoint, headers=headers, timeout=30)
                if response.status_code == 200:
                    data = response.json()
                    if isinstance(data, list):
                        logger.info(f"✅ Балансы успешно получены через эндпоинт: {endpoint}")
                        return data
            except Exception as e:
                logger.error(f"❌ Исключение при запросе к {endpoint}: {e}")
        
        logger.error("❌ Не удалось получить данные о балансах ни с одного эндпоинта.")
        return None

    async def get_specific_balance(self, currency: str) -> float | None:
        raw_balances = await self._get_raw_balances()
        if raw_balances:
            for item in raw_balances:
                if item.get('currency', '').lower() == currency.lower():
                    return float(item.get('balance', 0.0))
        return None

    async def get_current_bid_price(self, market_symbol: str) -> float | None:
        """Получение цены с гибким парсингом и отладкой."""
        await self.init()
        if not self.scraper:
            return None

        try:
            url = f"{self.base_url}/trade/public/tickers/{market_symbol}"
            response = await asyncio.to_thread(self.scraper.get, url, timeout=30)

            if response.status_code == 200:
                data = response.json()
                # Логируем ответ, чтобы точно знать его структуру
                logger.info(f"DEBUG: Полный ответ от API тикера ({market_symbol}): {json.dumps(data)}")

                price = 0.0
                
                # Проверяем разные возможные структуры ответа
                if isinstance(data, dict):
                    if 'ticker' in data and isinstance(data['ticker'], dict):
                        price = float(data['ticker'].get('bid', 0.0))
                    if price == 0.0 and 'bid' in data:
                        price = float(data.get('bid', 0.0))
                    if price == 0.0 and 'buy' in data: # Альтернативный ключ
                        price = float(data.get('buy', 0.0))

                if price > 0:
                    logger.info(f"✅ Цена для {market_symbol} успешно найдена: {price}")
                    return price
                else:
                    logger.warning(f"⚠️ Не удалось найти валидную цену 'bid' в ответе: {data}")
                    return None
            else:
                logger.error(f"❌ Ошибка получения цены. Статус: {response.status_code}, Ответ: {response.text[:200]}")
                return None
        except Exception as e:
            logger.error(f"❌ Исключение при получении цены: {e}", exc_info=True)
            return None

    # Другие методы (create_sell_order, format_order_success и т.д.) остаются без изменений.
    # ...

После замены класса SafeTradeClient на этот код, перезапустите бота и попробуйте снова. Теперь в логах вы увидите детальный ответ от API, и, скорее всего, одна из проверок в get_current_bid_price успешно найдет цену.
