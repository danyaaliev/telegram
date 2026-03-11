import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
import sqlite3
from datetime import datetime
from flask import Flask
import threading

# ===== НАСТРОЙКИ =====
# ВАЖНО: Токен берем из переменных окружения!
BOT_TOKEN = os.environ.get("TELEGRAM_TOKEN", "8544834677:AAG_KVEmN2d-ISrPxNjtKE3EAF0Rgu6gyjg")
# Для админов тоже лучше использовать переменные окружения
ADMIN_IDS_STR = os.environ.get("ADMIN_IDS", "1310415005,5189109518")
ADMIN_IDS = [int(x.strip()) for x in ADMIN_IDS_STR.split(",")]

# ===== FLASK ДЛЯ HEALTH CHECKS =====
app = Flask(__name__)

@app.route('/')
def home():
    return "Bot is running!"

@app.route('/health')
def health():
    return "OK", 200

def run_flask():
    """Запуск Flask сервера в отдельном потоке"""
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port)

# ===== ОСНОВНОЙ КОД БОТА =====
# Настройка логирования
logging.basicConfig(level=logging.INFO)

# Инициализация бота и диспетчера
bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

# Состояния для FSM
class AdminStates(StatesGroup):
    waiting_for_answer = State()  # Ожидание ответа администратора
    waiting_for_user_id = State()  # Ожидание ID пользователя для ответа

# Инициализация базы данных
def init_db():
    # Используем абсолютный путь для базы данных
    db_path = os.path.join(os.path.dirname(__file__), 'questions.db')
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    # Таблица вопросов
    c.execute('''CREATE TABLE IF NOT EXISTS questions
                 (id INTEGER PRIMARY KEY AUTOINCREMENT,
                  user_id INTEGER,
                  question_text TEXT,
                  question_time TIMESTAMP,
                  answered INTEGER DEFAULT 0,
                  answer_text TEXT,
                  answer_time TIMESTAMP,
                  answer_admin_id INTEGER)''')
    # Таблица забаненных пользователей
    c.execute('''CREATE TABLE IF NOT EXISTS banned_users
                 (user_id INTEGER PRIMARY KEY)''')
    conn.commit()
    conn.close()

# Проверка, забанен ли пользователь
def is_banned(user_id):
    db_path = os.path.join(os.path.dirname(__file__), 'questions.db')
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT user_id FROM banned_users WHERE user_id = ?", (user_id,))
    result = c.fetchone()
    conn.close()
    return result is not None

# Добавление вопроса в базу
def save_question(user_id, question_text):
    db_path = os.path.join(os.path.dirname(__file__), 'questions.db')
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("INSERT INTO questions (user_id, question_text, question_time) VALUES (?, ?, ?)",
              (user_id, question_text, datetime.now()))
    conn.commit()
    question_id = c.lastrowid
    conn.close()
    return question_id

# Сохранение ответа
def save_answer(question_id, answer_text, admin_id):
    db_path = os.path.join(os.path.dirname(__file__), 'questions.db')
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("UPDATE questions SET answered = 1, answer_text = ?, answer_time = ?, answer_admin_id = ? WHERE id = ?",
              (answer_text, datetime.now(), admin_id, question_id))
    conn.commit()
    conn.close()

# Получение неотвеченных вопросов
def get_unanswered_questions():
    db_path = os.path.join(os.path.dirname(__file__), 'questions.db')
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT id, user_id, question_text, question_time FROM questions WHERE answered = 0 ORDER BY question_time")
    questions = c.fetchall()
    conn.close()
    return questions

# Получение вопроса по ID
def get_question_by_id(question_id):
    db_path = os.path.join(os.path.dirname(__file__), 'questions.db')
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("SELECT id, user_id, question_text FROM questions WHERE id = ?", (question_id,))
    question = c.fetchone()
    conn.close()
    return question

# Бан пользователя
def ban_user(user_id):
    db_path = os.path.join(os.path.dirname(__file__), 'questions.db')
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("INSERT OR IGNORE INTO banned_users (user_id) VALUES (?)", (user_id,))
    conn.commit()
    conn.close()

# Разбан пользователя
def unban_user(user_id):
    db_path = os.path.join(os.path.dirname(__file__), 'questions.db')
    conn = sqlite3.connect(db_path)
    c = conn.cursor()
    c.execute("DELETE FROM banned_users WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

# Проверка, является ли пользователь администратором
def is_admin(user_id):
    return user_id in ADMIN_IDS

# Команда /start для обычных пользователей
@dp.message(Command("start"))
async def cmd_start(message: Message):
    if is_banned(message.from_user.id):
        await message.answer("⛔ Вы заблокированы и не можете отправлять вопросы.")
        return
    
    welcome_text = (
        "👋 Добро пожаловать в бота для анонимных вопросов!\n\n"
        "📝 Вы можете отправить любой вопрос анонимно, и администраторы смогут на него ответить.\n\n"
        "Просто напишите ваш вопрос в этот чат, и он будет передан администраторам.\n\n"
        "⚠️ Ваши личные данные (имя, username) не будут видны администраторам."
    )
    await message.answer(welcome_text)

# Команда /admin для администраторов
@dp.message(Command("admin"))
async def cmd_admin(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет прав для использования этой команды.")
        return
    
    questions = get_unanswered_questions()
    
    if not questions:
        await message.answer("📭 Нет неотвеченных вопросов.")
        return
    
    await message.answer(f"📋 Найдено неотвеченных вопросов: {len(questions)}\n\nИспользуйте /list для просмотра всех вопросов или /answer ID для ответа на конкретный вопрос.")

# Команда /list для просмотра всех неотвеченных вопросов
@dp.message(Command("list"))
async def cmd_list(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет прав для использования этой команды.")
        return
    
    questions = get_unanswered_questions()
    
    if not questions:
        await message.answer("📭 Нет неотвеченных вопросов.")
        return
    
    for i, (q_id, user_id, q_text, q_time) in enumerate(questions[:10], 1):
        time_str = datetime.fromisoformat(q_time).strftime("%d.%m.%Y %H:%M")
        question_preview = q_text[:50] + "..." if len(q_text) > 50 else q_text
        text = f"{i}. Вопрос #{q_id}\nОт: {user_id}\nВремя: {time_str}\nТекст: {question_preview}\n"
        
        keyboard = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="✏️ Ответить", callback_data=f"answer_{q_id}"),
             InlineKeyboardButton(text="⛔ Забанить", callback_data=f"ban_{user_id}")]
        ])
        
        await message.answer(text, reply_markup=keyboard)
    
    if len(questions) > 10:
        await message.answer(f"Показано 10 из {len(questions)} вопросов. Используйте /answer ID для ответа на конкретный вопрос.")

# Команда /answer для ответа на вопрос
@dp.message(Command("answer"))
async def cmd_answer(message: Message, state: FSMContext):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет прав для использования этой команды.")
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Укажите ID вопроса. Пример: /answer 5")
        return
    
    try:
        question_id = int(args[1])
    except ValueError:
        await message.answer("❌ ID вопроса должен быть числом.")
        return
    
    question = get_question_by_id(question_id)
    if not question:
        await message.answer("❌ Вопрос с таким ID не найден.")
        return
    
    await state.update_data(question_id=question_id, user_id=question[1])
    await state.set_state(AdminStates.waiting_for_answer)
    
    await message.answer(f"✏️ Введите ответ на вопрос #{question_id} (от пользователя {question[1]}):\n\nТекст вопроса: {question[2]}")

# Обработка текстовых сообщений от пользователей (новые вопросы)
@dp.message(F.text)
async def handle_user_question(message: Message, state: FSMContext):
    user_id = message.from_user.id
    
    if is_banned(user_id):
        await message.answer("⛔ Вы заблокированы и не можете отправлять вопросы.")
        return
    
    current_state = await state.get_state()
    if current_state == AdminStates.waiting_for_answer.state:
        # Это ответ администратора
        await handle_admin_answer(message, state)
        return
    
    # Это вопрос от обычного пользователя
    question_text = message.text
    
    question_id = save_question(user_id, question_text)
    
    # Уведомляем всех администраторов
    for admin_id in ADMIN_IDS:
        try:
            keyboard = InlineKeyboardMarkup(inline_keyboard=[
                [InlineKeyboardButton(text="✏️ Ответить", callback_data=f"answer_{question_id}"),
                 InlineKeyboardButton(text="⛔ Забанить", callback_data=f"ban_{user_id}")]
            ])
            
            await bot.send_message(
                admin_id,
                f"📨 Новый анонимный вопрос #{question_id}!\n\n"
                f"Текст: {question_text}\n\n"
                f"Нажмите кнопку ниже, чтобы ответить.",
                reply_markup=keyboard
            )
        except Exception as e:
            logging.error(f"Не удалось отправить уведомление админу {admin_id}: {e}")
    
    await message.answer("✅ Ваш вопрос отправлен администраторам. Как только они ответят, вы получите уведомление!")

# Обработка ответов администраторов
async def handle_admin_answer(message: Message, state: FSMContext):
    data = await state.get_data()
    question_id = data.get('question_id')
    user_id = data.get('user_id')
    answer_text = message.text
    
    save_answer(question_id, answer_text, message.from_user.id)
    
    try:
        await bot.send_message(
            user_id,
            f"📬 Вы получили ответ на ваш вопрос!\n\n"
            f"❓ Ваш вопрос: {get_question_by_id(question_id)[2]}\n"
            f"💬 Ответ: {answer_text}"
        )
    except Exception as e:
        logging.error(f"Не удалось отправить ответ пользователю {user_id}: {e}")
        await message.answer("❌ Не удалось отправить ответ пользователю (возможно, он заблокировал бота).")
    
    await message.answer(f"✅ Ответ на вопрос #{question_id} отправлен пользователю!")
    await state.clear()

# Обработка callback-кнопок
@dp.callback_query()
async def process_callback(callback: CallbackQuery, state: FSMContext):
    data = callback.data
    
    if data.startswith("answer_"):
        question_id = int(data.split("_")[1])
        question = get_question_by_id(question_id)
        
        if not question:
            await callback.answer("❌ Вопрос не найден!", show_alert=True)
            return
        
        await state.update_data(question_id=question_id, user_id=question[1])
        await state.set_state(AdminStates.waiting_for_answer)
        
        await callback.message.edit_text(
            f"✏️ Введите ответ на вопрос #{question_id} (от пользователя {question[1]}):\n\n"
            f"Текст вопроса: {question[2]}\n\n"
            f"(Отправьте ответ в чат)"
        )
        await callback.answer()
    
    elif data.startswith("ban_"):
        user_id = int(data.split("_")[1])
        ban_user(user_id)
        
        try:
            await callback.message.edit_text(
                callback.message.text + "\n\n✅ Пользователь забанен."
            )
        except:
            pass
        
        await callback.answer(f"✅ Пользователь {user_id} забанен", show_alert=True)

# Команда для добавления нового администратора
@dp.message(Command("addadmin"))
async def cmd_add_admin(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Только главный администратор может добавлять новых.")
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Укажите ID пользователя. Пример: /addadmin 123456789")
        return
    
    try:
        new_admin_id = int(args[1])
    except ValueError:
        await message.answer("❌ ID должен быть числом.")
        return
    
    if new_admin_id not in ADMIN_IDS:
        ADMIN_IDS.append(new_admin_id)
        await message.answer(f"✅ Пользователь {new_admin_id} добавлен в администраторы.")
    else:
        await message.answer("ℹ️ Этот пользователь уже администратор.")

# Команда для удаления администратора
@dp.message(Command("removeadmin"))
async def cmd_remove_admin(message: Message):
    if message.from_user.id not in ADMIN_IDS:
        await message.answer("⛔ Только главный администратор может удалять администраторов.")
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Укажите ID пользователя. Пример: /removeadmin 123456789")
        return
    
    try:
        admin_id = int(args[1])
    except ValueError:
        await message.answer("❌ ID должен быть числом.")
        return
    
    if admin_id in ADMIN_IDS and admin_id != message.from_user.id:
        ADMIN_IDS.remove(admin_id)
        await message.answer(f"✅ Пользователь {admin_id} удален из администраторов.")
    elif admin_id == message.from_user.id:
        await message.answer("❌ Нельзя удалить самого себя.")
    else:
        await message.answer("❌ Пользователь не является администратором.")

# Команда для разбана
@dp.message(Command("unban"))
async def cmd_unban(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ У вас нет прав для использования этой команды.")
        return
    
    args = message.text.split()
    if len(args) < 2:
        await message.answer("❌ Укажите ID пользователя. Пример: /unban 123456789")
        return
    
    try:
        user_id = int(args[1])
    except ValueError:
        await message.answer("❌ ID должен быть числом.")
        return
    
    unban_user(user_id)
    await message.answer(f"✅ Пользователь {user_id} разбанен.")

# Функция запуска бота
async def run_bot():
    """Запуск бота в отдельном потоке"""
    init_db()
    logging.info("Бот запущен...")
    await dp.start_polling(bot)

def main():
    """Главная функция"""
    # Запускаем Flask в отдельном потоке
    flask_thread = threading.Thread(target=run_flask, daemon=True)
    flask_thread.start()
    
    # Запускаем бота в основном потоке
    asyncio.run(run_bot())

if __name__ == "__main__":
    main()