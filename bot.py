import os
import requests
import logging
from datetime import datetime
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, CallbackQueryHandler, ContextTypes
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import signal
import sys
import time

# ========== ПРОСТОЙ HTTP СЕРВЕР ДЛЯ RENDER PING ==========
class HealthHandler(BaseHTTPRequestHandler):
    def do_HEAD(self):
        """Для UptimeRobot (бесплатный план)"""
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
    
    def do_GET(self):
        """Для ручной проверки в браузере"""
        self.send_response(200)
        self.send_header('Content-type', 'text/plain')
        self.end_headers()
        self.wfile.write('OK Bot'.encode('utf-8'))
    
    def log_message(self, format, *args):
        pass  # Отключаем логи запросов

def run_health_server():
    """Запускает HTTP сервер для health checks"""
    port = int(os.environ.get('PORT', 10000))
    server = HTTPServer(('0.0.0.0', port), HealthHandler)
    print(f"✅ Health server started on port {port}")
    server.serve_forever()

# Запускаем health server в отдельном потоке
health_thread = threading.Thread(target=run_health_server, daemon=True)
health_thread.start()

# ========== НАСТРОЙКИ БОТА ==========
SPREADSHEET_ID = "17VDwwzNG7ZLM-HAmTTApW5NARkDsieH22D7vg5_jTCA"
SHEETS = {
    "Список_карт_номиналов": "0",
    "Список_номеров_СБП": "2146222680"
}

# Токен из переменных окружения Render
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========== МОНИТОРИНГ РЕСУРСОВ ==========
def check_resources():
    """Проверка использования памяти"""
    try:
        import psutil
        process = psutil.Process()
        memory_mb = process.memory_info().rss / 1024 / 1024
        
        if memory_mb > 400:  # Близко к лимиту 512MB
            logger.warning(f"⚠️ Высокое использование памяти: {memory_mb:.1f}MB")
            return False
        return True
    except:
        return True  # Если не удалось проверить, продолжаем работу

def resource_monitor():
    """Фоновая проверка ресурсов каждые 30 минут"""
    while True:
        time.sleep(1800)  # 30 минут
        if not check_resources():
            logger.error("🔄 Превышение лимита памяти, перезапуск...")
            os._exit(1)  # Принудительный перезапуск

# ========== АВТОПЕРЕЗАПУСК ЧЕРЕЗ 48 ЧАСОВ ==========
def auto_restart_timer():
    """Принудительный перезапуск каждые 48 часов"""
    time.sleep(172800)  # 48 часов = 2 дня
    logger.info("⏰ Время планового перезапуска (48 часов)")
    print("=" * 60)
    print("🔄 Плановый перезапуск для предотвращения падений")
    print("=" * 60)
    os._exit(0)

# ========== ФУНКЦИИ БОТА ==========
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /start"""
    user = update.effective_user
    await update.message.reply_text(
        f"👋 Привет {user.first_name}!\n"
        f"Я бот для выгрузки данных из Платежного Щита.\n\n"
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
        
        files_sent = 0
        
        for sheet_name, gid in SHEETS.items():
            try:
                # Скачиваем CSV
                url = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv&gid={gid}"
                response = requests.get(url, timeout=30)
                response.raise_for_status()
                
                # Определяем красивое имя файла
                if sheet_name == "Список_карт_номиналов":
                    filename = "Список карт номиналов.csv"
                elif sheet_name == "Список_номеров_СБП":
                    filename = "Список номеров СБП.csv"
                else:
                    filename = f"{sheet_name}.csv"
                
                # Отправляем файл
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
            final_msg = f"✅ Отправлено {files_sent} файлов"
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
        "/status - Проверка состояния\n"
        "/help - Справка"
    )

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /status - проверка работы бота"""
    import psutil
    import os
    
    process = psutil.Process(os.getpid())
    memory_mb = process.memory_info().rss / 1024 / 1024
    uptime = time.time() - process.create_time()
    
    hours = int(uptime // 3600)
    minutes = int((uptime % 3600) // 60)
    
    await update.message.reply_text(
        f"📊 Статус бота:\n"
        f"• Работает: {hours}ч {minutes}м\n"
        f"• Память: {memory_mb:.1f} MB\n"
        f"• Состояние: ✅ Активен\n"
        f"• Перезапуск через: {48-hours}ч {59-minutes}м"
    )

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Обработчик ошибок"""
    logger.error(f"Ошибка: {context.error}")
    if update and update.effective_user:
        await context.bot.send_message(
            chat_id=update.effective_user.id,
            text="❌ Произошла ошибка. Попробуйте позже."
        )

# ========== ЗАПУСК БОТА С ЗАЩИТОЙ ==========
def main():
    """Основная функция с защитой от падений"""
    
    # Устанавливаем обработчики сигналов
    def signal_handler(signum, frame):
        logger.info(f"🚦 Получен сигнал {signum}, завершаем работу...")
        sys.exit(0)
    
    signal.signal(signal.SIGTERM, signal_handler)
    
    # Логируем старт
    start_time = datetime.now()
    logger.info(f"🚀 Бот запущен: {start_time}")
    print("=" * 60)
    print("🛡️  Защищенный бот запущен")
    print(f"📅 Старт: {start_time}")
    print("⏰ Автоперезапуск через 48 часов")
    print("📊 Мониторинг памяти каждые 30 минут")
    print("=" * 60)
    
    # Проверка токена
    if not TOKEN:
        logger.error("❌ TELEGRAM_BOT_TOKEN не установлен!")
        print("ОШИБКА: Добавьте TELEGRAM_BOT_TOKEN в Environment Variables на Render!")
        return
    
    # Запускаем мониторинг ресурсов
    monitor_thread = threading.Thread(target=resource_monitor, daemon=True)
    monitor_thread.start()
    
    # Запускаем таймер автоперезапуска
    restart_thread = threading.Thread(target=auto_restart_timer, daemon=True)
    restart_thread.start()
    
    try:
        # Создаем приложение
        application = Application.builder().token(TOKEN).build()
        
        # Регистрируем обработчики
        application.add_handler(CommandHandler("start", start))
        application.add_handler(CommandHandler("download", download_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("status", status_command))
        application.add_handler(CallbackQueryHandler(button_handler))
        
        # Обработчик ошибок
        application.add_error_handler(error_handler)
        
        # Запускаем бота
        logger.info("🤖 Бот запущен и ожидает сообщений...")
        application.run_polling()
        
    except Exception as e:
        logger.error(f"Критическая ошибка: {e}")
        print(f"❌ Ошибка запуска: {e}")
        
        # Пытаемся перезапуститься через 60 секунд
        print("🔄 Перезапуск через 60 секунд...")
        time.sleep(60)
        os._exit(1)  # Завершаем процесс для перезапуска Render

if __name__ == "__main__":
    # Бесконечный цикл перезапуска при падениях
    while True:
        try:
            main()
        except KeyboardInterrupt:
            print("\n👋 Завершение работы...")
            break
        except Exception as e:
            print(f"💥 Критическая ошибка в основном цикле: {e}")
            print("🔄 Перезапуск через 30 секунд...")
            time.sleep(30)
