import os
import requests
import logging
import csv
import io
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, ContextTypes
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import signal
import sys
import time
from openpyxl import Workbook
from openpyxl.styles import Font, PatternFill, Alignment, Border, Side
from openpyxl.utils import get_column_letter

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

# Внутренние ключи листов (используются для ID в Google Sheets)
SHEETS = {
    "Список_карт_номиналов": "0",
    "Список_номеров_СБП": "2146222680"
}

# Красивые имена для отображения в xlsx (без подчёркиваний, с пробелами)
SHEET_DISPLAY_NAMES = {
    "Список_карт_номиналов": "Список карт номиналов",
    "Список_номеров_СБП": "Список номеров СБП",
}

# Эталонные столбцы для каждого листа (по базовому имени, без месяца).
# При сборке xlsx заголовок CSV будет заменён на эти имена,
# а число колонок в каждой строке приведено к эталону:
#   - лишние колонки обрезаются
#   - недостающие дополняются пустыми строками
EXPECTED_COLUMNS = {
    "Список карт номиналов": [
        "Дата",
        "Карта",
        "Название Казино",
        "Зеркало (URL)",
        "Платежная система (URL)",
        "ФИО",
        "Название банка",
    ],
    "Список номеров СБП": [
        "Дата",
        "Номер СБП",
        "Название Казино",
        "Зеркало (URL)",
        "Платежная система (URL)",
        "ФИО",
        "Название банка",
        "Доп. инфо",
    ],
}

# Замены значений ячеек в xlsx по имени столбца.
# Если ячейка содержит любой из keywords (case-insensitive substring) —
# вся ячейка заменяется на replacement.
# Применяется ТОЛЬКО к xlsx; оригинальные CSV не модифицируются.
COLUMN_REPLACEMENTS = {
    "Название банка": [
        {"keywords": ["сбер", "sber"], "replacement": "ПАО Сбербанк"},
    ],
}

# Русские названия месяцев (явный словарь — не зависит от системной локали Render)
RU_MONTHS = {
    1: "Январь", 2: "Февраль", 3: "Март", 4: "Апрель",
    5: "Май", 6: "Июнь", 7: "Июль", 8: "Август",
    9: "Сентябрь", 10: "Октябрь", 11: "Ноябрь", 12: "Декабрь"
}


def get_current_month_name() -> str:
    """Возвращает название текущего месяца по-русски (с заглавной буквы)."""
    return RU_MONTHS.get(datetime.now().month, "Неизвестно")


def get_sheet_display_name(sheet_key: str, month_name: str = None) -> str:
    """
    Формирует отображаемое имя листа с текущим месяцем.
    Например: 'Список карт номиналов.Октябрь'
    """
    base = SHEET_DISPLAY_NAMES.get(sheet_key, sheet_key.replace("_", " "))
    if month_name:
        return f"{base}.{month_name}"
    return base

# Токен из переменных окружения Render
TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "")

# Логирование
logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ========== СТИЛИЗАЦИЯ XLSX (СТИЛЬ "ЩИТ") ==========
# Тёмно-зелёный хедер с белым жирным шрифтом
HEADER_FILL = PatternFill(start_color="FF1B5E20", end_color="FF1B5E20", fill_type="solid")
HEADER_FONT = Font(name="Calibri", size=11, bold=True, color="FFFFFFFF")
HEADER_ALIGN = Alignment(horizontal="center", vertical="center", wrap_text=True)

# Обычные ячейки
CELL_FONT = Font(name="Calibri", size=11)
CELL_ALIGN = Alignment(vertical="center", wrap_text=False)
CELL_FILL_ALT = PatternFill(start_color="FFF1F8E9", end_color="FFF1F8E9", fill_type="solid")  # светло-зелёный для чётных строк

# Тонкая серая рамка
THIN_BORDER = Border(
    left=Side(style="thin", color="FFCCCCCC"),
    right=Side(style="thin", color="FFCCCCCC"),
    top=Side(style="thin", color="FFCCCCCC"),
    bottom=Side(style="thin", color="FFCCCCCC"),
)

# Максимальная ширина колонки (в символах)
MAX_COL_WIDTH = 60
MIN_COL_WIDTH = 10


def sanitize_sheet_name(name: str) -> str:
    """Приводит имя листа к требованиям Excel: ≤31 символ, без : \\ / ? * [ ]"""
    for ch in ":\\/?*[]":
        name = name.replace(ch, "_")
    return name[:31]


def get_base_display_name(sheet_name: str) -> str:
    """
    Возвращает базовое имя листа без суффикса месяца.
    'Список карт номиналов.Октябрь' → 'Список карт номиналов'
    Если совпадения нет — возвращает исходное имя как есть.
    """
    if sheet_name in EXPECTED_COLUMNS:
        return sheet_name
    if "." in sheet_name:
        base = sheet_name.rsplit(".", 1)[0]
        if base in EXPECTED_COLUMNS:
            return base
    return sheet_name


def normalize_row_to_expected(row: list, expected_columns: list) -> list:
    """
    Подгоняет строку данных под ожидаемое число колонок:
    - если в row больше значений — лишние обрезаются
    - если меньше — дополняется пустыми строками
    """
    expected_count = len(expected_columns)
    if len(row) >= expected_count:
        return row[:expected_count]
    return row + [""] * (expected_count - len(row))


def apply_expected_columns(rows: list, sheet_name: str) -> tuple:
    """
    Если для листа заданы эталонные столбцы — заменяет заголовок CSV на эталонный
    и приводит все строки данных к ожидаемому числу колонок.

    :param rows: строки CSV (первая строка — заголовок)
    :param sheet_name: имя листа (с месяцем или без)
    :return: (новые_строки, базовое_имя) — для логирования
    """
    base_name = get_base_display_name(sheet_name)
    expected_cols = EXPECTED_COLUMNS.get(base_name)
    if not expected_cols:
        return rows, base_name

    if not rows:
        # Нет данных, но есть эталонный заголовок — выведем только его
        return [list(expected_cols)], base_name

    data_rows = rows[1:]  # без старого заголовка
    new_rows = [list(expected_cols)] + [
        normalize_row_to_expected(r, expected_cols) for r in data_rows
    ]
    return new_rows, base_name


def apply_column_replacements(rows: list) -> int:
    """
    Применяет замены значений ячеек по правилам COLUMN_REPLACEMENTS.
    Работает по имени столбца (из заголовка), поэтому универсальна для всех листов.

    :param rows: строки CSV (первая строка — заголовок)
    :return: количество заменённых ячеек
    """
    if not rows or len(rows) < 2:
        return 0

    header = rows[0]
    replacements_count = 0

    # Собираем индексы колонок, к которым применимы правила
    applicable_cols = []
    for col_idx, col_name in enumerate(header):
        if col_name and col_name in COLUMN_REPLACEMENTS:
            applicable_cols.append((col_idx, COLUMN_REPLACEMENTS[col_name]))

    if not applicable_cols:
        return 0

    for row in rows[1:]:
        for col_idx, rules in applicable_cols:
            if col_idx >= len(row):
                continue
            val = row[col_idx]
            if not val or not isinstance(val, str):
                continue
            val_lower = val.lower()
            for rule in rules:
                if any(kw.lower() in val_lower for kw in rule["keywords"]):
                    row[col_idx] = rule["replacement"]
                    replacements_count += 1
                    break  # одно правило уже сработало
    return replacements_count


def parse_csv(content: bytes):
    """
    Парсит CSV из байтов в список строк.
    Удаляет полностью пустые строки и обрезает лишние пробелы в ячейках.
    """
    text = content.decode("utf-8-sig", errors="replace")
    reader = csv.reader(io.StringIO(text))
    rows = []
    for row in reader:
        # Пропускаем полностью пустые строки (все ячейки пустые или только пробелы)
        if not any(cell and cell.strip() for cell in row):
            continue
        # Чистим каждую ячейку: убираем лишние пробелы по краям
        cleaned = [cell.strip() if isinstance(cell, str) else cell for cell in row]
        rows.append(cleaned)
    return rows


def build_xlsx(sheets_data: dict) -> bytes:
    """
    Собирает один xlsx-файл из нескольких CSV.

    :param sheets_data: {sheet_name: csv_bytes}
    :return: xlsx-файл в виде байтов
    """
    wb = Workbook()
    # Удаляем дефолтный лист, который openpyxl создаёт автоматически
    wb.remove(wb.active)

    for sheet_name, csv_bytes in sheets_data.items():
        rows = parse_csv(csv_bytes)
        ws = wb.create_sheet(title=sanitize_sheet_name(sheet_name))

        # Если для этого листа заданы эталонные столбцы — заменяем заголовок CSV
        # на эталонный и приводим число колонок в каждой строке к эталону
        rows, base_name = apply_expected_columns(rows, sheet_name)
        if base_name in EXPECTED_COLUMNS:
            logger.info(
                f"Лист '{sheet_name}': применены эталонные столбцы "
                f"({len(EXPECTED_COLUMNS[base_name])} шт.), "
                f"строк данных: {max(len(rows) - 1, 0)}"
            )

        # Применяем замены значений ячеек по правилам COLUMN_REPLACEMENTS
        # (только в xlsx; оригинальные CSV не трогаются)
        replacements = apply_column_replacements(rows)
        if replacements > 0:
            logger.info(f"Лист '{sheet_name}': заменено {replacements} ячеек по COLUMN_REPLACEMENTS")

        if not rows:
            ws["A1"] = "Нет данных"
            ws.column_dimensions["A"].width = MIN_COL_WIDTH
            continue

        # Записываем данные
        for r_idx, row in enumerate(rows, start=1):
            for c_idx, value in enumerate(row, start=1):
                # ВСЕ ячейки сохраняем как текст — чтобы не терялись ведущие нули у
                # номеров карт/СБП, большие числа не превращались в 1.23E+18, и т.д.
                cell = ws.cell(row=r_idx, column=c_idx, value=value)
                cell.number_format = "@"  # текстовый формат
                cell.border = THIN_BORDER
                if r_idx == 1:
                    # Заголовок колонки
                    cell.fill = HEADER_FILL
                    cell.font = HEADER_FONT
                    cell.alignment = HEADER_ALIGN
                else:
                    cell.font = CELL_FONT
                    cell.alignment = CELL_ALIGN
                    # Чередование строк для читаемости (зебра)
                    if r_idx % 2 == 0:
                        cell.fill = CELL_FILL_ALT

        # Авто-ширина колонок (учитываем, что кириллица шире латиницы)
        max_col = ws.max_column
        max_row = ws.max_row
        for col_idx in range(1, max_col + 1):
            col_letter = get_column_letter(col_idx)
            max_length = 0
            for row_idx in range(1, min(max_row, 200) + 1):  # ограничиваем 200 строками для скорости
                cell = ws.cell(row=row_idx, column=col_idx)
                if cell.value is not None:
                    v = str(cell.value)
                    # Кириллица и др. не-ASCII = 1.1, латиница = 1
                    length = sum(1.1 if ord(c) > 127 else 1 for c in v)
                    if length > max_length:
                        max_length = length
            ws.column_dimensions[col_letter].width = min(max(max_length + 2, MIN_COL_WIDTH), MAX_COL_WIDTH)

        # Заморозка первой строки
        ws.freeze_panes = "A2"

        # Авто-фильтр по заголовкам
        try:
            ws.auto_filter.ref = f"A1:{get_column_letter(max_col)}{max_row}"
        except Exception as e:
            logger.warning(f"Не удалось установить авто-фильтр для листа {sheet_name}: {e}")

    # Если ни одного листа не создалось — добавим пустой
    if not wb.sheetnames:
        ws = wb.create_sheet(title="Пусто")
        ws["A1"] = "Нет данных"

    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


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
        f"Используй /download чтобы получить сводный xlsx-файл + исходные CSV."
    )
    logger.info(f"Пользователь {user.id} запустил бота")


async def download_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /download - сразу скачивает и присылает xlsx + CSV без кнопки"""
    user = update.effective_user
    logger.info(f"Пользователь {user.id} запросил /download")

    # Определяем текущий месяц для имён листов
    month_name = get_current_month_name()
    logger.info(f"Текущий месяц для имён листов: {month_name}")

    # Скачиваем все CSV в память, ключи — отображаемые имена с месяцем
    sheets_data = {}
    errors = []
    for sheet_key, gid in SHEETS.items():
        display_name = get_sheet_display_name(sheet_key, month_name)
        try:
            url = f"https://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}/export?format=csv&gid={gid}"
            response = requests.get(url, timeout=30)
            response.raise_for_status()
            sheets_data[display_name] = response.content
            logger.info(f"Скачан лист '{display_name}': {len(response.content)} байт")
        except Exception as e:
            logger.error(f"Ошибка скачивания {display_name}: {e}")
            errors.append(f"{display_name}: {str(e)[:80]}")

    if not sheets_data:
        await update.message.reply_text(
            "❌ Не удалось скачать ни один лист из Google Sheets"
        )
        return

    # Собираем один общий xlsx
    try:
        xlsx_bytes = build_xlsx(sheets_data)
    except Exception as e:
        logger.error(f"Ошибка сборки xlsx: {e}")
        await update.message.reply_text(f"❌ Ошибка при сборке xlsx: {str(e)[:100]}")
        return

    # Файл всегда называется pls.xlsx (имя фиксированное, без даты)
    filename = "pls.xlsx"
    year_str = datetime.now().strftime("%Y")

    # Подсчёт строк в каждом листе для отчёта
    sheet_stats = []
    for name, csv_bytes in sheets_data.items():
        rows = parse_csv(csv_bytes)
        sheet_stats.append(f"• {name}: {len(rows)} строк")

    caption = (
        f"🛡️ SHIELD — {month_name} {year_str}\n\n"
        + "\n".join(sheet_stats)
    )
    if errors:
        caption += f"\n\n⚠️ Не скачано: {len(errors)}"

    await context.bot.send_document(
        chat_id=update.effective_chat.id,
        document=xlsx_bytes,
        filename=filename,
        caption=caption
    )
    logger.info(f"Отправлен файл: {filename} ({len(xlsx_bytes)} байт) пользователю {user.id}")

    # Дополнительно отправляем оригинальные CSV-файлы по каждому листу отдельно
    for display_name, csv_bytes in sheets_data.items():
        # Имя CSV: <имя листа>.csv — с месяцем для консистентности с xlsx
        csv_filename = f"{display_name}.csv"
        try:
            await context.bot.send_document(
                chat_id=update.effective_chat.id,
                document=csv_bytes,
                filename=csv_filename,
            )
            logger.info(f"Отправлен CSV: {csv_filename} ({len(csv_bytes)} байт)")
        except Exception as e:
            logger.error(f"Ошибка отправки CSV {csv_filename}: {e}")
            await update.message.reply_text(f"❌ Не удалось отправить {csv_filename}")

    logger.info(f"Завершено для пользователя {user.id}")


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Команда /help"""
    await update.message.reply_text(
        "📚 Доступные команды:\n"
        "/start - Начать работу\n"
        "/download - Получить сводный xlsx + исходные CSV\n"
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
        f"• Перезапуск через: {max(48-hours, 0)}ч {max(59-minutes, 0)}м"
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
    print("📥 Сборка одного сводного xlsx с именами листов по текущему месяцу")
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
