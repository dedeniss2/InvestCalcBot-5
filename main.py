import logging
import sqlite3
import asyncio
from datetime import datetime
import yfinance as yf
from telegram import Update, ReplyKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# Настройка логирования
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO)
logger = logging.getLogger(__name__)

# Токен Telegram-бота (получите новый от @BotFather, если не работает)
TOKEN = "7654401250:AAG2U97kJZRYos7za6bS2QZyN3Y-6KFpJnE"

# Путь к базе данных SQLite
DB_PATH = "investments.db"

# Кнопки
REPLY_KEYBOARD = ReplyKeyboardMarkup(
    [["📊 Портфель", "➕ Добавить"], ["➖ Удалить", "⚠️ Алерты"]],
    resize_keyboard=True)

# Создание таблицы в базе данных
def init_db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    cursor = conn.cursor()
    cursor.execute('''CREATE TABLE IF NOT EXISTS investments
                     (asset TEXT, price_min REAL, price_max REAL)''')
    conn.commit()
    conn.close()

# Функция для получения цены актива
async def get_asset_price(ticker: str, attempt: int = 1, max_attempts: int = 3) -> float:
    try:
        data = yf.Ticker(ticker).history(period="1d")
        if data.empty:
            logger.warning(f"Попытка {attempt} для {ticker} не удалась: Нет данных о ценах")
            if attempt < max_attempts:
                await asyncio.sleep(2)
                return await get_asset_price(ticker, attempt + 1, max_attempts)
            raise ValueError(f"Нет данных о ценах для {ticker} после {max_attempts} попыток")
        return data["Close"].iloc[-1]
    except Exception as e:
        logger.error(f"Ошибка при получении цены для {ticker}: {e}")
        if attempt < max_attempts:
            await asyncio.sleep(2)
            return await get_asset_price(ticker, attempt + 1, max_attempts)
        raise

# Функция для проверки алертов
async def check_alerts(application):
    logger.info("Проверка алертов начата")
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT asset, price_min, price_max FROM investments")
        tickers = cursor.fetchall()
        conn.close()

        for ticker, price_min, price_max in tickers:
            try:
                price = await get_asset_price(ticker)
                logger.info(f"✅ Текущая цена {ticker}: {price}")
                message = f"Цена {ticker}: {price:.2f}"
                if price_min and price < price_min:
                    message += f"\n⚠️ Цена ниже минимума ({price_min})!"
                if price_max and price > price_max:
                    message += f"\n⚠️ Цена выше максимума ({price_max})!"
                await application.bot.send_message(chat_id=784622780, text=message)
            except Exception as e:
                logger.error(f"❌ Ошибка при проверке {ticker}: {e}")
                await application.bot.send_message(chat_id=784622780, text=f"Ошибка для {ticker}: {e}")
    except Exception as e:
        logger.error(f"Ошибка в check_alerts: {e}")

# Команда /start
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Получена команда /start от chat_id: {update.message.chat_id}")
    await update.message.reply_text(
        "Бот запущен! Используйте кнопки или команды: /portfolio, /add_ticker, /remove_ticker, /list_tickers, /set_alert",
        reply_markup=REPLY_KEYBOARD)

# Команда /portfolio или /list_tickers
async def portfolio(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Получена команда /portfolio от chat_id: {update.message.chat_id}")
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        cursor = conn.cursor()
        cursor.execute("SELECT DISTINCT asset, price_min, price_max FROM investments")
        tickers = cursor.fetchall()
        conn.close()
        if tickers:
            message = "📊 Ваш портфель:\n\n"
            message += "Тикer | Мин. цена | Макс. цена\n"
            message += "------|-----------|-----------\n"
            for ticker, price_min, price_max in tickers:
                message += f"{ticker:<6} | {price_min or 'не задан':<10} | {price_max or 'не задан':<10}\n"
            await update.message.reply_text(f"<pre>{message}</pre>", parse_mode="HTML")
        else:
            await update.message.reply_text("📊 Ваш портфель пуст.", reply_markup=REPLY_KEYBOARD)
    except sqlite3.OperationalError as e:
        logger.error(f"Ошибка базы данных при получении портфеля: {e}")
        await update.message.reply_text(f"Ошибка базы данных: {e}", reply_markup=REPLY_KEYBOARD)
    except Exception as e:
        logger.error(f"Ошибка при получении портфеля: {e}")
        await update.message.reply_text(f"Ошибка: {e}", reply_markup=REPLY_KEYBOARD)

# Команда /add_ticker
async def add_ticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Получена команда /add_ticker от chat_id: {update.message.chat_id}")
    if not context.args:
        await update.message.reply_text("Укажите тикer, например: /add_ticker TSLA", reply_markup=REPLY_KEYBOARD)
        return
    ticker = context.args[0].upper()
    try:
        price = await get_asset_price(ticker)
        conn = sqlite3.connect(DB_PATH, timeout=10)
        cursor = conn.cursor()
        cursor.execute("INSERT INTO investments (asset) VALUES (?)", (ticker,))
        conn.commit()
        conn.close()
        await update.message.reply_text(f"➕ Тикer {ticker} добавлен в портфель. Цена: {price:.2f}", reply_markup=REPLY_KEYBOARD)
    except sqlite3.OperationalError as e:
        logger.error(f"Ошибка базы данных при добавлении тикера {ticker}: {e}")
        await update.message.reply_text(f"Ошибка базы данных: {e}", reply_markup=REPLY_KEYBOARD)
    except Exception as e:
        logger.error(f"Ошибка при добавлении тикера {ticker}: {e}")
        await update.message.reply_text(f"Ошибка при добавлении {ticker}: {e}", reply_markup=REPLY_KEYBOARD)

# Команда /remove_ticker
async def remove_ticker(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Получена команда /remove_ticker от chat_id: {update.message.chat_id}")
    if not context.args:
        await update.message.reply_text("Укажите тикer, например: /remove_ticker TSLA", reply_markup=REPLY_KEYBOARD)
        return
    ticker = context.args[0].upper()
    try:
        conn = sqlite3.connect(DB_PATH, timeout=10)
        cursor = conn.cursor()
        cursor.execute("DELETE FROM investments WHERE asset = ?", (ticker,))
        conn.commit()
        if cursor.rowcount > 0:
            await update.message.reply_text(f"➖ Тикer {ticker} удалён из портфеля.", reply_markup=REPLY_KEYBOARD)
        else:
            await update.message.reply_text(f"Тикer {ticker} не найден в портфеле.", reply_markup=REPLY_KEYBOARD)
        conn.close()
    except sqlite3.OperationalError as e:
        logger.error(f"Ошибка базы данных при удалении тикера {ticker}: {e}")
        await update.message.reply_text(f"Ошибка базы данных: {e}", reply_markup=REPLY_KEYBOARD)
    except Exception as e:
        logger.error(f"Ошибка при удалении тикера {ticker}: {e}")
        await update.message.reply_text(f"Ошибка при удалении {ticker}: {e}", reply_markup=REPLY_KEYBOARD)

# Команда /set_alert
async def set_alert(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.info(f"Получена команда /set_alert от chat_id: {update.message.chat_id}")
    if len(context.args) != 3:
        await update.message.reply_text("Укажите тикer, минимум и максимум, например: /set_alert TSLA 200 300", reply_markup=REPLY_KEYBOARD)
        return
    ticker = context.args[0].upper()
    try:
        price_min = float(context.args[1])
        price_max = float(context.args[2])
        conn = sqlite3.connect(DB_PATH, timeout=10)
        cursor = conn.cursor()
        cursor.execute("UPDATE investments SET price_min = ?, price_max = ? WHERE asset = ?", (price_min, price_max, ticker))
        conn.commit()
        if cursor.rowcount > 0:
            await update.message.reply_text(f"⚠️ Алерт для {ticker} установлен: мин {price_min}, макс {price_max}", reply_markup=REPLY_KEYBOARD)
        else:
            await update.message.reply_text(f"Тикer {ticker} не найден в портфеле.", reply_markup=REPLY_KEYBOARD)
        conn.close()
    except ValueError:
        await update.message.reply_text("Минимум и максимум должны быть числами, например: /set_alert TSLA 200 300", reply_markup=REPLY_KEYBOARD)
    except sqlite3.OperationalError as e:
        logger.error(f"Ошибка базы данных при установке алерта для {ticker}: {e}")
        await update.message.reply_text(f"Ошибка базы данных: {e}", reply_markup=REPLY_KEYBOARD)
    except Exception as e:
        logger.error(f"Ошибка при установке алерта для {ticker}: {e}")
        await update.message.reply_text(f"Ошибка: {e}", reply_markup=REPLY_KEYBOARD)

# Обработка текстовых сообщений (кнопок)
async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text
    logger.info(f"Получено сообщение '{text}' от chat_id: {update.message.chat_id}")
    if text == "📊 Портфель":
        await portfolio(update, context)
    elif text == "➕ Добавить":
        await update.message.reply_text("Введите тикer, например: /add_ticker TSLA", reply_markup=REPLY_KEYBOARD)
    elif text == "➖ Удалить":
        await update.message.reply_text("Укажите тикer, например: /remove_ticker TSLA", reply_markup=REPLY_KEYBOARD)
    elif text == "⚠️ Алерты":
        await update.message.reply_text("Установите алерт, например: /set_alert TSLA 200 300", reply_markup=REPLY_KEYBOARD)
    else:
        await update.message.reply_text("Неизвестная команда. Используйте кнопки или команды: /portfolio, /add_ticker, /remove_ticker, /set_alert", reply_markup=REPLY_KEYBOARD)

# Главная функция
async def main():
    # Создание приложения
    application = Application.builder().token(TOKEN).build()

    # Добавление обработчиков команд
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("portfolio", portfolio))
    application.add_handler(CommandHandler("list_tickers", portfolio))
    application.add_handler(CommandHandler("add_ticker", add_ticker))
    application.add_handler(CommandHandler("remove_ticker", remove_ticker))
    application.add_handler(CommandHandler("set_alert", set_alert))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Инициализация базы данных
    init_db()

    # Инициализация планировщика
    scheduler = AsyncIOScheduler()
    scheduler.add_job(check_alerts, "interval", hours=1, args=[application])
    scheduler.start()
    logger.info("Планировщик запущен")

    # Запуск бота с polling
    logger.info("Запуск бота с polling...")
    await application.run_polling()

if __name__ == "__main__":
    asyncio.run(main())
