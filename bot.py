import os
import requests
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes

# ========== НАСТРОЙКИ ==========
SPREADSHEET_ID = "14x5PZnq9AX8CcRW1cl5hyne0IndtNh0L"
SHEETS = {
    "Список_карт_номиналов": "1674053030",
    "Список_номеров_СБП": "1789244637"
}

# Токен будет из переменных окружения Render
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========== ФУНКЦИИ БОТА ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    user = update.effective_user
    await update.message.reply_text(
        f"👋 Привет {user.first_name}!\n"
        f"Я бот для выгрузки данных из Google Sheets.\n\n"
        f"Используй /download чтобы получить файлы CSV."
    )
    logger.info(f"Пользователь {user.id} запустил бота")

async def download_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /download - показывает кнопку"""
    keyboard = [[InlineKeyboardButton("📥 Скачать CSV файлы", callback_data='download_csv')]]
    reply_markup = InlineKeyboardMarkup(keyboard)
    
    await update.message.reply_text("Нажмите кнопку для скачивания файлов:", reply_markup=reply_markup)
    logger.info(f"Пользователь {update.effective_user.id} запросил файлы")

async def button_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик нажатия на кнопку"""
    query = update.callback_query
    await query.answer()
    
    if query.data == 'download_csv':
        user = query.from_user
        logger.info(f"Пользователь {user.id} нажал кнопку скачивания")
        await query.edit_message_text("⏳ Скачиваю файлы...")
        
        date_str = datetime.now().strftime("%Y-%m-%d_%H-%M")
        files_sent = 0
        
        for sheet_name, gid in SHEETS.items():
            try:
                # Скачиваем CSV
                url = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv&gid={gid}"
                response = requests.get(url, timeout=30)
                response.raise_for_status()
                
                # Отправляем файл
                filename = f"{sheet_name}_{date_str}.csv"
                await context.bot.send_document(
                    chat_id=query.message.chat_id,
                    document=response.content,
                    filename=filename,
                    caption=f"📊 {sheet_name}"
                )
                
                files_sent += 1
                logger.info(f"Отправлен файл: {filename}")
                
            except Exception as e:
                logger.error(f"Ошибка скачивания {sheet_name}: {e}")
                await context.bot.send_message(
                    chat_id=query.message.chat_id,
                    text=f"❌ Ошибка при скачивании {sheet_name}: {str(e)[:100]}"
                )
        
        if files_sent > 0:
            final_msg = f"✅ Отправлено {files_sent} файлов\nДата: {date_str}"
        else:
            final_msg = "❌ Не удалось скачать файлы"
            
        await context.bot.send_message(chat_id=query.message.chat_id, text=final_msg)
        logger.info(f"Завершено для пользователя {user.id}: {final_msg}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help"""
    await update.message.reply_text(
        "📚 Доступные команды:\n"
        "/start - Начать работу\n"
        "/download - Получить CSV файлы\n"
        "/help - Справка"
    )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error(f"Ошибка: {context.error}")
    if update and update.effective_user:
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text="❌ Произошла ошибка. Попробуйте позже."
        )

# ========== ЗАПУСК БОТА ==========
def main():
    """Основная функция"""
    logger.info("Запуск бота...")
    
    if not TOKEN:
        logger.error("❌ TELEGRAM_BOT_TOKEN не установлен!")
        print("ОШИБКА: Добавьте TELEGRAM_BOT_TOKEN в Environment Variables на Render!")
        return
    
    try:
        # Создаем приложение
        application = Application.builder().token(TOKEN).build()
        
        # Регистрируем обработчики
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("download", download_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CallbackQueryHandler(button_handler))
        
        # Обработчик ошибок
        application.add_error_handler(error_handler)
        
        # Запускаем бота
        logger.info("🤖 Бот запущен и ожидает сообщений...")
        print("=" * 50)
        print("Бот успешно запущен на Render!")
        print(f"Имя бота: Sheets Downloader")
        print("Ожидаю сообщений в Telegram...")
        print("=" * 50)
        
        application.run_polling()
        
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        print(f"❌ Ошибка запуска: {e}")

if __name__ == "__main__":
    main()
