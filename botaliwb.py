import requests
import sqlite3
import csv
from bs4 import BeautifulSoup
from aiogram import Bot, Dispatcher, types
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.utils import executor
from aiogram.dispatcher.filters import Command

# === Ваш Telegram токен ===
TELEGRAM_BOT_TOKEN = "8043845844:AAGh8vYhucLpxOWJGFn4ZCUHTzVv6oUqCtw"

# === Инициализация бота ===
bot = Bot(token=TELEGRAM_BOT_TOKEN)
dp = Dispatcher(bot)

# === База данных для хранения истории запросов ===
DB_NAME = "search_history.db"
CSV_FILE = "search_history.csv"

def init_db():
    """Создает таблицу для истории запросов, если она еще не существует"""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("""
        CREATE TABLE IF NOT EXISTS history (
            user_id INTEGER,
            platform TEXT,
            query TEXT,
            price_from INTEGER,
            price_to INTEGER,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP
        )
        """)
        conn.commit()

        # Создаем CSV файл, если он не существует
        with open(CSV_FILE, mode='a', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            writer.writerow(["user_id", "platform", "query", "price_from", "price_to", "timestamp"])

def save_to_csv(data, file_name="search_history.csv"):
    try:
        with open(file_name, mode='a', newline='', encoding='utf-8') as file:
            writer = csv.writer(file)
            for item in data:
                # Гарантируем, что данные корректно преобразованы в строковый формат
                writer.writerow([str(field) for field in item])
    except Exception as e:
        print(f"Ошибка записи в CSV: {e}")


def save_to_history(user_id, platform, query, price_from, price_to):
    """Сохраняет запрос пользователя в базу данных и CSV файл"""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("""
        INSERT INTO history (user_id, platform, query, price_from, price_to)
        VALUES (?, ?, ?, ?, ?)
        """, (user_id, platform, query, price_from, price_to))
        conn.commit()

    # Запись в CSV файл
    with open(CSV_FILE, mode='a', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow([user_id, platform, query, price_from, price_to])

def get_user_history(user_id):
    """Возвращает историю запросов пользователя"""
    with sqlite3.connect(DB_NAME) as conn:
        cursor = conn.cursor()
        cursor.execute("""
        SELECT platform, query, price_from, price_to, timestamp 
        FROM history 
        WHERE user_id = ? 
        ORDER BY timestamp DESC 
        LIMIT 10
        """, (user_id,))
        history = cursor.fetchall()

    # Экспорт истории в CSV файл при запросе
    with open(CSV_FILE, mode='a', newline='', encoding='utf-8') as file:
        writer = csv.writer(file)
        writer.writerow(["Exported History for User ID:", user_id])
        writer.writerows(history)

    return history

# === Хранение выбора пользователя ===
user_platform_choice = {}

# === Клавиатура для выбора платформы ===
platform_keyboard = ReplyKeyboardMarkup(resize_keyboard=True)
platform_keyboard.add(KeyboardButton("AliExpress"), KeyboardButton("Wildberries"))

# === Команда start ===
@dp.message_handler(Command("start"))
async def welcome(message: Message):
    await message.reply(
        "Привет! Выберите площадку для поиска товаров:",
        reply_markup=platform_keyboard
    )

# === Команда history ===
@dp.message_handler(Command("history"))
async def show_history(message: Message):
    user_id = message.from_user.id
    history = get_user_history(user_id)

    if not history:
        await message.reply("У вас пока нет истории запросов.")
        return

    reply_text = "\ud83d\udd4c *Ваша история запросов:*\n\n"
    for idx, (platform, query, price_from, price_to, timestamp) in enumerate(history, start=1):
        reply_text += f"{idx}. \ud83d\uded2 *{platform}* — _{query}_ от {price_from} до {price_to} руб. \n\ud83d\udd52 {timestamp}\n\n"

    await message.reply(reply_text, parse_mode="Markdown")

# === Обработчик выбора платформы ===
@dp.message_handler(lambda message: message.text in ["AliExpress", "Wildberries"])
async def choose_platform(message: Message):
    user_platform_choice[message.from_user.id] = message.text
    await message.reply(
        f"Отлично! Теперь ищем товары на {message.text}.\n"
        "Введите запрос и диапазон цен в формате: 'запрос от min до max'.\n\n"
        "Пример: `сумка от 500 до 1500`."
    )

# === Обработчик поиска товаров ===
@dp.message_handler()
async def search_products(message: Message):
    try:
        # Проверка выбора платформы
        platform = user_platform_choice.get(message.from_user.id)
        if not platform:
            await message.reply("Сначала выберите площадку для поиска товаров:", reply_markup=platform_keyboard)
            return

        # Парсим запрос пользователя
        query, price_from, price_to = parse_user_input(message.text)

        # Сохраняем запрос в базу данных
        save_to_history(message.from_user.id, platform, query, price_from, price_to)

        # Выполняем поиск на выбранной платформе
        if platform == "AliExpress":
            search_results = google_search_aliexpress(query, price_from, price_to)
        elif platform == "Wildberries":
            search_results = wildberries_search(query, price_from, price_to)

        # Формируем ответ
        if not search_results:
            await message.reply("Товары не найдены. Попробуйте изменить запрос или диапазон цен.")
            return

        reply_text = f"🔍 *Найденные товары на {platform}:*\n\n"
        for idx, (title, price, link) in enumerate(search_results[:10], start=1):
            reply_text += f"{idx}. [{title}]({link}) - {price}\n\n"

        await message.reply(reply_text, parse_mode="Markdown")
    except Exception as e:
        print(f"Ошибка: {e}")
        await message.reply("Произошла ошибка. Попробуйте позже.")


# === Функция парсинга ввода пользователя ===
def parse_user_input(user_input: str):
    parts = user_input.lower().split(" от ")
    query = parts[0].strip()
    price_range = parts[1].split(" до ")
    price_from = int(price_range[0].strip())
    price_to = int(price_range[1].strip())
    return query, price_from, price_to

# === Поиск на AliExpress через Google ===
def google_search_aliexpress(query, price_from, price_to):
    """
    Выполняет поиск в Google с фильтром по сайту AliExpress.
    Возвращает только ссылки на страницы товаров (без категорий или сборок).
    """
    search_query = f"{query} {price_from} - {price_to} site:aliexpress.com"
    url = f"https://www.google.com/search?q={search_query}&hl=ru&gl=ru"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36"
    }

    response = requests.get(url, headers=headers)
    soup = BeautifulSoup(response.text, "lxml")

    # Сбор и фильтрация результатов
    results = []
    for item in soup.find_all('div', class_='tF2Cxc'):  # Каждый блок результата поиска
        try:
            title = item.find('h3').text  # Заголовок результата
            link = item.find('a')['href']  # Ссылка на результат

            # Фильтруем только страницы товаров AliExpress
            if "aliexpress.com" in link and is_valid_aliexpress_link(link):
                results.append((title, link))
        except (AttributeError, TypeError):
            continue

    return results

def is_valid_aliexpress_link(link):
    """
    Проверяет, является ли ссылка страницей конкретного товара на AliExpress.
    Исключает категории, сборки и другие нерелевантные страницы.
    """
    invalid_keywords = ["category", "search", "wholesale", "collection", "stores"]
    if any(keyword in link for keyword in invalid_keywords):
        return False
    return "aliexpress.com/item/" in link or "aliexpress.com/i/" in link

    for item in soup.find_all('div', class_='tF2Cxc'):
        try:
            title = item.find('h3').text  # Заголовок результата
            link = item.find('a')['href']  # Ссылка на товар
            if "aliexpress.com" in link:  # Фильтрация по AliExpress
                results.append((title, link))
        except (AttributeError, TypeError):
            continue

    return results






# === Поиск на Wildberries через API ===
def wildberries_search(query, price_from, price_to):
    base_url = "https://search.wb.ru/exactmatch/ru/common/v4/search"
    params = {
        "TestGroup": "no_test",
        "TestID": "no_test",
        "appType": "1",
        "curr": "rub",
        "dest": "-1257786",
        "query": query,
        "priceU": f"{price_from * 100}-{price_to * 100}",  # Цены в копейках
        "resultset": "catalog",
        "spp": "20"
    }
    headers = {"User-Agent": "Mozilla/5.0"}

    try:
        response = requests.get(base_url, params=params, headers=headers)
        response.raise_for_status()
        data = response.json()

        # Логирование ответа для проверки
        print("Ответ от API Wildberries:", data)

        # Извлечение данных о товарах
        products = data.get("data", {}).get("products", [])
        results = []
        for product in products:
            title = product.get("name", "Без названия")
            product_id = product.get("id")
            price = product.get("salePriceU", 0) / 100  # Цена в рублях

            # Фильтруем товары по диапазону цен
            if price_from <= price <= price_to:
                link = f"https://www.wildberries.ru/catalog/{product_id}/detail.aspx"
                results.append((title, f"{price} руб.", link))

        return results
    except requests.RequestException as e:
        print(f"Ошибка при запросе к Wildberries API: {e}")
        return []
    except Exception as e:
        print(f"Неизвестная ошибка: {e}")
        return []



# === Обработчик ошибок и обработка ответа ===
async def handle_search_results(platform, query, price_from, price_to, user_id):
    try:
        # Выполнение поиска
        if platform == "AliExpress":
            results = google_search_aliexpress(query, price_from, price_to)
        elif platform == "Wildberries":
            results = wildberries_search(query, price_from, price_to)
        else:
            results = []

        # Формирование ответа
        if not results:
            return f"Товары по запросу \"{query}\" не найдены на платформе {platform}."

        response = f"\ud83d\udd0d *Результаты поиска на {platform}:*\n\n"
        for idx, (title, link) in enumerate(results[:15], start=1):
            response += f"{idx}. [{title}]({link})\n\n"
        return response
    except Exception as e:
        print(f"Ошибка обработки результатов: {e}")
        return "Произошла ошибка при обработке запроса. Пожалуйста, попробуйте снова позже."

# === Запуск процесса ===
if __name__ == "__main__":
    # Проверяем, что база данных и CSV файл инициализированы
    init_db()
    print("Бот запущен и готов к работе...")

    # Запуск бота
    executor.start_polling(dp, skip_updates=True)

