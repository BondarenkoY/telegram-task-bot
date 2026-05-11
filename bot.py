import sqlite3
import os

from dotenv import load_dotenv
from openpyxl import Workbook

from aiogram import Bot, Dispatcher, types
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.types import (
    InlineKeyboardMarkup,
    InlineKeyboardButton,
    ReplyKeyboardMarkup,
    KeyboardButton
)
from aiogram.utils import executor
from apscheduler.schedulers.asyncio import AsyncIOScheduler

# ================= CONFIG =================

load_dotenv()

SUPER_ADMIN = 251756272

API_TOKEN = os.environ["BOT_TOKEN"]
CHAT_ID = 251756272

# ================= INIT =================

bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)

scheduler = AsyncIOScheduler()

# ================= DATABASE =================

conn = sqlite3.connect("tasks.db", check_same_thread=False)
cursor = conn.cursor()

cursor.execute("""
CREATE TABLE IF NOT EXISTS tasks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT,
    responsible TEXT,
    period_start TEXT,
    period_end TEXT,
    status TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS periods (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    start_date TEXT,
    end_date TEXT,
    status TEXT
)
""")

cursor.execute("""
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    telegram_id INTEGER UNIQUE,
    name TEXT,
    role TEXT
)
""")

conn.commit()

cursor.execute("""
INSERT OR IGNORE INTO users (
    telegram_id,
    name,
    role
)
VALUES (?, ?, ?)
""", (
    SUPER_ADMIN,
    "Владелец",
    "admin"
))

conn.commit()

cursor.execute("""
CREATE TABLE IF NOT EXISTS pinned_message (
    id INTEGER PRIMARY KEY,
    message_id INTEGER
)
""")

conn.commit()

# ================= HELPERS =================

def get_user_role(user_id):

    user = cursor.execute("""
    SELECT role
    FROM users
    WHERE telegram_id=?
    """, (user_id,)).fetchone()

    if not user:
        return None

    return user[0]

async def update_pinned_message():

    period = get_active_period()

    if not period:
        return

    start, end = period

    tasks = cursor.execute("""
    SELECT * FROM tasks
    WHERE status='new'
    ORDER BY id ASC
    """).fetchall()

    text = (
        f"📅 Активная вахта\n"
        f"{start} → {end}\n\n"
    )

    if not tasks:

        text += "📭 Активных задач нет"

    else:

        text += "📋 Активные задачи:\n\n"

        for task in tasks:

            text += (
                f"{task[0]}. {task[1]}\n"
                f"👤 {task[2]}\n\n"
            )

    saved = cursor.execute("""
    SELECT message_id
    FROM pinned_message
    WHERE id=1
    """).fetchone()

    try:

        if saved:

            await bot.edit_message_text(
                chat_id=CHAT_ID,
                message_id=saved[0],
                text=text
            )

        else:

            msg = await bot.send_message(
                CHAT_ID,
                text
            )

            await bot.pin_chat_message(
                CHAT_ID,
                msg.message_id
            )

            cursor.execute("""
            INSERT OR REPLACE INTO pinned_message (
                id,
                message_id
            )
            VALUES (1, ?)
            """, (msg.message_id,))

            conn.commit()

    except Exception as e:
        print(e)

class AddTaskState(StatesGroup):
    waiting_for_text = State()
    waiting_for_responsible = State()

class EditTaskState(StatesGroup):
    waiting_for_new_text = State()

class AddUserState(StatesGroup):

    waiting_for_id = State()

def is_allowed(user_id):

    role = get_user_role(user_id)

    return role in ["admin", "worker"]

def is_admin(user_id):

    return get_user_role(user_id) == "admin"


def is_worker(user_id):

    return get_user_role(user_id) == "worker"

def get_active_period():
    return cursor.execute(
        "SELECT start_date, end_date FROM periods WHERE status='active'"
    ).fetchone()


def task_keyboard(task_id):

    keyboard = InlineKeyboardMarkup()

    keyboard.add(

        InlineKeyboardButton(
            "✅ Выполнено",
            callback_data=f"done:{task_id}"
        ),

        InlineKeyboardButton(
            "❌ Не выполнено",
            callback_data=f"fail:{task_id}"
        )
    )

    keyboard.add(

        InlineKeyboardButton(
            "✏️ Редактировать",
            callback_data=f"edit:{task_id}"
        ),

        InlineKeyboardButton(
            "🗑 Удалить",
            callback_data=f"delete:{task_id}"
        )
    )

    return keyboard

def responsible_keyboard():

    keyboard = ReplyKeyboardMarkup(
        resize_keyboard=True
    )

    workers = cursor.execute("""
    SELECT name
    FROM users
    WHERE role='worker'
    ORDER BY name
    """).fetchall()

    for worker in workers:

        keyboard.add(
            KeyboardButton(f"👤 {worker[0]}")
        )

    keyboard.add(
        KeyboardButton("⬅️ Назад")
    )

    return keyboard

def archive_keyboard(periods):

    keyboard = InlineKeyboardMarkup()

    for period in periods:

        start, end = period

        keyboard.add(
            InlineKeyboardButton(
                f"📅 {start} → {end}",
                callback_data=f"archive:{start}:{end}"
            )
        )

    return keyboard

def close_period_keyboard(periods):

    keyboard = InlineKeyboardMarkup()

    for period in periods:

        start, end = period

        keyboard.add(
            InlineKeyboardButton(
                f"📅 {start} → {end}",
                callback_data=f"closeperiod:{start}:{end}"
            )
        )

    return keyboard

def main_menu(user_id):

    keyboard = ReplyKeyboardMarkup(
        resize_keyboard=True
    )

    role = get_user_role(user_id)

    if role == "admin":

        keyboard.add(
            KeyboardButton("➕ Добавить задачу"),
            KeyboardButton("📋 Список задач")
        )

        keyboard.add(
            KeyboardButton("📅 Установить вахту"),
            KeyboardButton("🔒 Закрыть вахту")
        )

        keyboard.add(
            KeyboardButton("📁 Архив"),
            KeyboardButton("📤 Excel отчет")
        )

        keyboard.add(
            KeyboardButton("👥 Персонал")
        )

    elif role == "worker":

        keyboard.add(
            KeyboardButton("📋 Список задач")
        )

    return keyboard

def personnel_menu():

    keyboard = ReplyKeyboardMarkup(
        resize_keyboard=True
    )

    keyboard.add(
        KeyboardButton("➕ Добавить админа"),
        KeyboardButton("➕ Добавить работника")
    )

    keyboard.add(
        KeyboardButton("📋 Список персонала"),
        KeyboardButton("🗑 Удалить пользователя")
    )

    keyboard.add(
        KeyboardButton("⬅️ Назад")
    )

    return keyboard

# ================= AUTO REPORT =================

async def send_pre_report():

    rows = cursor.execute("""
    SELECT * FROM tasks
    WHERE status='new'
    """).fetchall()

    if not rows:
        return

    text = "⚠️ Предварительный список задач:\n\n"

    for r in rows:
        text += f"{r[0]}. {r[1]} — {r[2]}\n"

    await bot.send_message(CHAT_ID, text)

# ================= ROTATE TASKS =================

# ================= ROTATE TASKS =================

async def rotate_tasks():

    period = get_active_period()

    if not period:
        return

    start, end = period

    cursor.execute("""
    UPDATE tasks
    SET status='pending_transfer'
    WHERE status='failed'
    AND period_start=?
    AND period_end=?
    """, (start, end))

    cursor.execute("""
    UPDATE periods
    SET status='closed'
    WHERE start_date=?
    AND end_date=?
    """, (start, end))

    conn.commit()

    await bot.send_message(
        CHAT_ID,
        f"✅ Вахта закрыта:\n"
        f"{start} → {end}\n\n"
        f"Невыполненные задачи ждут переноса"
    )

# ================= PERIOD =================

@dp.message_handler(commands=['set_period'])
async def set_period(message: types.Message):

    if not is_admin(message.from_user.id):
        await message.reply("❌ Нет доступа")
        return

    try:

        parts = message.text.replace(
            "/set_period ",
            ""
        ).split("|")

        start, end = [p.strip() for p in parts]

        cursor.execute("DELETE FROM periods")

        cursor.execute("""
        INSERT INTO periods (
            start_date,
            end_date,
            status
        )
        VALUES (?, ?, 'active')
        """, (start, end))

        conn.commit()

        pending_tasks = cursor.execute("""
        SELECT * FROM tasks
        WHERE status='pending_transfer'
        """).fetchall()

        for task in pending_tasks:

            cursor.execute("""
            INSERT INTO tasks (
                text,
                responsible,
                period_start,
                period_end,
                status
            )
            VALUES (?, ?, ?, ?, 'new')
            """, (
                task[1],
                task[2],
                start,
                end
            ))

            cursor.execute("""
            UPDATE tasks
            SET status='archived'
            WHERE id=?
            """, (task[0],))

        conn.commit()

        await update_pinned_message()

        await message.reply(
            f"✅ Период установлен:\n{start} - {end}"
        )
    except Exception as e:

        print(e)

        await message.reply(
            "Формат:\n"
            "/set_period 2026-05-10 | 2026-05-17"
        )        
        await message.reply(
            "Формат:\n"
            "/set_period 2026-05-10 | 2026-05-17"
        )

# ================= ADD TASK =================

@dp.message_handler(commands=['add'])
async def add_task(message: types.Message):

    if not is_admin(message.from_user.id):
        await message.reply("❌ Нет доступа")
        return

    try:

        parts = message.text.replace(
            "/add ",
            ""
        ).split("|")

        text = parts[0].strip()
        responsible = parts[1].strip()

        period = get_active_period()

        if not period:
            await message.reply(
                "❌ Сначала задай вахту"
            )
            return

        start, end = period

        cursor.execute("""
        INSERT INTO tasks (
            text,
            responsible,
            period_start,
            period_end,
            status
        )
        VALUES (?, ?, ?, ?, 'new')
        """, (
            text,
            responsible,
            start,
            end
        ))

        conn.commit()

        await update_pinned_message()

        await message.reply(
            "✅ Задача добавлена"
        )

    except Exception as e:

        if "Message is not modified" in str(e):
            pass
        else:
            print(e)

        await message.reply(
            "Формат:\n"
            "/add Проверить насос | Иван"
        )

# ================= LIST TASKS =================

@dp.message_handler(commands=['list'])
async def list_tasks(message: types.Message):

    if not is_allowed(message.from_user.id):
        await message.reply("❌ Нет доступа")
        return

    rows = cursor.execute("""
    SELECT * FROM tasks
    WHERE status='new'
    ORDER BY id DESC
    """).fetchall()

    if not rows:
        await message.reply("📭 Активных задач нет")
        return

    for r in rows:

        text = (
            f"📋 Задача #{r[0]}\n\n"
            f"🛠 {r[1]}\n"
            f"👤 Ответственный: {r[2]}\n"
            f"📅 {r[3]} → {r[4]}\n"
            f"📌 Статус: {r[5]}"
        )

        await message.reply(
            text,
            reply_markup=task_keyboard(r[0])
        )

# ================= BUTTON MENU =================

@dp.message_handler(
    lambda message: message.text == "👥 Персонал"
)
async def open_personnel_menu(
    message: types.Message
):

    if not is_admin(message.from_user.id):
        return

    await message.reply(
        "👥 Управление персоналом",
        reply_markup=personnel_menu()
    )

@dp.message_handler(
    lambda message: message.text == "➕ Добавить работника"
)
async def add_worker_start(
    message: types.Message,
    state: FSMContext
):

    if not is_admin(message.from_user.id):
        return

    await state.update_data(role="worker")
    await AddUserState.waiting_for_id.set()

    await message.reply(
        "Отправь:\n\n"
        "ID | Имя\n\n"
        "Пример:\n"
        "123456789 | Иван"
    )

@dp.message_handler(
    state=AddUserState.waiting_for_id
)
async def save_worker(
    message: types.Message,
    state: FSMContext
):

    try:

        parts = message.text.split("|")

        telegram_id = int(parts[0].strip())
        name = parts[1].strip()

        data = await state.get_data()

        role = data.get("role", "worker")

        cursor.execute("""
        INSERT OR REPLACE INTO users (
            telegram_id,
            name,
            role
        )
        VALUES (?, ?, ?)
        """, (
            telegram_id,
            name,
            role
        ))

        conn.commit()

        await state.finish()

        await message.reply(
            f"✅ {role} {name} добавлен",
            reply_markup=personnel_menu()
        )

    except Exception as e:

        print(e)

        await message.reply(
            "❌ Формат:\n"
            "123456789 | Иван"
        )

@dp.message_handler(
    lambda message: message.text == "📋 Список персонала"
)
async def personnel_list(
    message: types.Message
):

    if not is_admin(message.from_user.id):
        return

    rows = cursor.execute("""
    SELECT *
    FROM users
    ORDER BY role, name
    """).fetchall()

    if not rows:

        await message.reply(
            "📭 Персонал пуст"
        )

        return

    text = "👥 Персонал\n\n"

    for user in rows:

        text += (
            f"👤 {user[2]}\n"
            f"🆔 {user[1]}\n"
            f"🔑 {user[3]}\n\n"
        )

    await message.reply(text)

@dp.message_handler(lambda message: message.text == "📋 Список задач")
async def button_list(message: types.Message):
    await list_tasks(message)


@dp.message_handler(lambda message: message.text == "🔒 Закрыть вахту")
async def button_close_period(message: types.Message):

    if not is_admin(message.from_user.id):
        await message.reply("❌ Нет доступа")
        return

    periods = cursor.execute("""
    SELECT DISTINCT period_start, period_end
    FROM tasks
    WHERE status='new'
    ORDER BY period_start DESC
    """).fetchall()

    if not periods:

        await message.reply(
            "❌ Нет открытых вахт"
        )

        return

    await message.reply(
        "📅 Выберите вахту для закрытия:",
        reply_markup=close_period_keyboard(periods)
    )

@dp.message_handler(lambda message: message.text == "📊 Статистика")
async def statistics(message: types.Message):

    done_count = cursor.execute("""
    SELECT COUNT(*)
    FROM tasks
    WHERE status='done'
    """).fetchone()[0]

    failed_count = cursor.execute("""
    SELECT COUNT(*)
    FROM tasks
    WHERE status='failed'
    """).fetchone()[0]

    await message.reply(
        f"📊 Статистика:\n\n"
        f"✅ Выполнено: {done_count}\n"
        f"❌ Не выполнено: {failed_count}"
    )


@dp.message_handler(lambda message: message.text == "➕ Добавить задачу")
async def add_task_start(message: types.Message):

    if not is_admin(message.from_user.id):
        await message.reply("❌ Нет доступа")
        return

    await AddTaskState.waiting_for_text.set()

    await message.reply(
        "🛠 Введите текст задачи"
    )


@dp.message_handler(state=AddTaskState.waiting_for_text)
async def add_task_text(
    message: types.Message,
    state: FSMContext
):

    await state.update_data(
        task_text=message.text
    )

    await AddTaskState.waiting_for_responsible.set()

    await message.reply(
    "👤 Выберите ответственного",
    reply_markup=responsible_keyboard()
)


@dp.message_handler(state=AddTaskState.waiting_for_responsible)
async def add_task_responsible(
    message: types.Message,
    state: FSMContext
):

    data = await state.get_data()

    task_text = data["task_text"]

    responsible = (
        message.text
        .replace("👤 ", "")
        .strip()
    )

    worker = cursor.execute("""
    SELECT *
    FROM users
    WHERE role='worker'
    AND name=?
    """, (responsible,)).fetchone()

    if not worker:

        await message.reply(
            "❌ Выберите сотрудника кнопкой"
        )

        return

    period = get_active_period()

    if not period:
        await message.reply(
            "❌ Сначала установи вахту"
        )

        await state.finish()
        return

    start, end = period

    cursor.execute("""
    INSERT INTO tasks (
        text,
        responsible,
        period_start,
        period_end,
        status
    )
    VALUES (?, ?, ?, ?, 'new')
    """, (
        task_text,
        responsible,
        start,
        end
    ))

    conn.commit()

    await update_pinned_message()

    await message.reply(
        "✅ Задача добавлена",
        reply_markup=main_menu(message.from_user.id)
    )

    await state.finish()

@dp.message_handler(lambda message: message.text == "📅 Установить вахту")
async def set_period_help(message: types.Message):

    await message.reply(
        "Введи период:\n\n"
        "/set_period 2026-05-10 | 2026-05-17"
    )
@dp.message_handler(lambda message: message.text == "📁 Архив")
async def archive_tasks(message: types.Message):

    if not is_allowed(message.from_user.id):
        await message.reply("❌ Нет доступа")
        return

    periods = cursor.execute("""
    SELECT DISTINCT period_start, period_end
    FROM tasks
    WHERE status != 'new'
    ORDER BY period_start DESC
    LIMIT 10
    """).fetchall()

    if not periods:
        await message.reply("📁 Архив пуст")
        return

    await message.reply(
        "📁 Выберите вахту:",
        reply_markup=archive_keyboard(periods)
    )

# ================= CLOSE PERIOD =================

@dp.message_handler(commands=['close_period'])
async def close_period(message: types.Message):

    if not is_admin(message.from_user.id):
        await message.reply("❌ Нет доступа")
        return

    await rotate_tasks()

    await message.reply("✅ Вахта закрыта")

# ================= CALLBACKS =================

@dp.callback_query_handler(
    lambda c: c.data.startswith(("done", "fail"))
)
async def process_task_status(
    callback_query: types.CallbackQuery
):

    if not is_allowed(callback_query.from_user.id):
        await callback_query.answer("❌ Нет доступа")
        return

    action, task_id = callback_query.data.split(":")

    status = (
        "done"
        if action == "done"
        else "failed"
    )

    cursor.execute("""
    UPDATE tasks
    SET status=?
    WHERE id=?
    """, (status, task_id))

    conn.commit()

    await update_pinned_message()

    await callback_query.answer(
        "Статус обновлен"
    )

    await callback_query.message.edit_reply_markup()

    await callback_query.message.reply(
        f"✅ Задача #{task_id} "
        f"обновлена: {status}"
    )
@dp.callback_query_handler(
    lambda c: c.data.startswith("archive:")
)
async def archive_period_view(
    callback_query: types.CallbackQuery
):

    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("❌ Нет доступа")
        return

    _, start, end = callback_query.data.split(":")

    tasks = cursor.execute("""
    SELECT * FROM tasks
    WHERE period_start=?
    AND period_end=?
    AND status != 'new'
    ORDER BY id DESC
    """, (start, end)).fetchall()

    if not tasks:

        await callback_query.message.reply(
            "📁 В этой вахте нет задач"
        )

        return

    text = (
        f"📅 Вахта:\n"
        f"{start} → {end}\n\n"
    )

    for task in tasks:

        status_emoji = (
            "✅"
            if task[5] == "done"
            else "❌"
        )

        text += (
            f"{status_emoji} #{task[0]}\n"
            f"🛠 {task[1]}\n"
            f"👤 {task[2]}\n"
            f"📌 {task[5]}\n\n"
        )

    await callback_query.message.reply(text)

@dp.callback_query_handler(
    lambda c: c.data.startswith("edit:")
)
async def edit_task_menu(
    callback_query: types.CallbackQuery
):

    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("❌ Нет доступа")
        return

    task_id = callback_query.data.split(":")[1]

    keyboard = InlineKeyboardMarkup()

    keyboard.add(
        InlineKeyboardButton(
            "🛠 Изменить текст",
            callback_data=f"edittext:{task_id}"
        )
    )

    keyboard.add(
        InlineKeyboardButton(
            "👤 Изменить ответственного",
            callback_data=f"editresp:{task_id}"
        )
    )

    await callback_query.message.reply(
        "✏️ Что изменить?",
        reply_markup=keyboard
    )
@dp.callback_query_handler(
    lambda c: c.data.startswith("edittext:")
)
async def edit_text_start(
    callback_query: types.CallbackQuery,
    state: FSMContext
):

    task_id = callback_query.data.split(":")[1]

    await state.update_data(
        edit_task_id=task_id
    )

    await EditTaskState.waiting_for_new_text.set()

    await callback_query.message.reply(
        "🛠 Введите новый текст задачи"
    )


@dp.message_handler(state=EditTaskState.waiting_for_new_text)
async def save_new_text(
    message: types.Message,
    state: FSMContext
):

    data = await state.get_data()

    task_id = data["edit_task_id"]

    cursor.execute("""
    UPDATE tasks
    SET text=?
    WHERE id=?
    """, (
        message.text,
        task_id
    ))

    conn.commit()

    await message.reply(
        "✅ Текст задачи обновлен",
        reply_markup=main_menu(message.from_user.id)
    )

    await state.finish()
@dp.callback_query_handler(
    lambda c: c.data.startswith("editresp:")
)
async def edit_responsible_start(
    callback_query: types.CallbackQuery,
    state: FSMContext
):

    task_id = callback_query.data.split(":")[1]

    await state.update_data(
        edit_resp_task_id=task_id
    )

    await callback_query.message.reply(
        "👤 Выберите нового ответственного",
        reply_markup=responsible_keyboard()
    )


@dp.message_handler(
    lambda message: message.text.startswith("👤 "),
    state="*"
)

async def save_new_responsible(
    message: types.Message,
    state: FSMContext
):

    data = await state.get_data()

    if "edit_resp_task_id" not in data:
        return

    if "edit_resp_task_id" not in data:
        return

    responsible = (
        message.text
        .replace("👤 ", "")
        .strip()
    )

    task_id = data["edit_resp_task_id"]

    cursor.execute("""
    UPDATE tasks
    SET responsible=?
    WHERE id=?
    """, (
        responsible,
        task_id
    ))

    conn.commit()

    await message.reply(
        "✅ Ответственный обновлен",
        reply_markup=main_menu(message.from_user.id)
    )

    await state.finish()

@dp.callback_query_handler(
    lambda c: c.data.startswith("delete:")
)
async def delete_task_confirm(
    callback_query: types.CallbackQuery
):

    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("❌ Нет доступа")
        return

    task_id = callback_query.data.split(":")[1]

    keyboard = InlineKeyboardMarkup()

    keyboard.add(

        InlineKeyboardButton(
            "✅ Да",
            callback_data=f"confirmdelete:{task_id}"
        ),

        InlineKeyboardButton(
            "❌ Нет",
            callback_data="canceldelete"
        )
    )

    await callback_query.message.reply(
        f"⚠️ Удалить задачу #{task_id}?",
        reply_markup=keyboard
    )
@dp.callback_query_handler(
    lambda c: c.data.startswith("confirmdelete:")
)
async def delete_task_execute(
    callback_query: types.CallbackQuery
):

    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("❌ Нет доступа")
        return

    task_id = callback_query.data.split(":")[1]

    cursor.execute("""
    DELETE FROM tasks
    WHERE id=?
    """, (task_id,))

    conn.commit()

    await update_pinned_message()

    await callback_query.message.reply(
        f"🗑 Задача #{task_id} удалена"
    )


@dp.callback_query_handler(
    lambda c: c.data == "canceldelete"
)
async def cancel_delete(
    callback_query: types.CallbackQuery
):

    await callback_query.message.reply(
        "❌ Удаление отменено"
    )

@dp.message_handler(
    lambda message: message.text == "📤 Excel отчет"
)
async def export_excel(
    message: types.Message
):

    if not is_admin(message.from_user.id):
        await message.reply("❌ Нет доступа")
        return

    rows = cursor.execute("""
    SELECT * FROM tasks
    ORDER BY id DESC
    """).fetchall()

    if not rows:
        await message.reply("📭 Нет задач")
        return

    wb = Workbook()
    ws = wb.active

    ws.title = "Tasks"

    headers = [
        "ID",
        "Задача",
        "Ответственный",
        "Начало",
        "Конец",
        "Статус"
    ]

    ws.append(headers)

    for row in rows:

        ws.append([
            row[0],
            row[1],
            row[2],
            row[3],
            row[4],
            row[5]
        ])

    filename = "tasks_report.xlsx"

    wb.save(filename)

    with open(filename, "rb") as file:

        await bot.send_document(
            message.chat.id,
            file,
            caption="📤 Excel отчет"
        )

# ================= START =================

@dp.message_handler(lambda message: message.text == "⬅️ Назад", state="*")
async def back_to_menu(
    message: types.Message,
    state: FSMContext
):

    await state.finish()

    await message.reply(
        "↩️ Возврат в главное меню",
        reply_markup=main_menu(message.from_user.id)
    )

@dp.callback_query_handler(
    lambda c: c.data.startswith("closeperiod:")
)
async def confirm_close_period(
    callback_query: types.CallbackQuery
):

    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("❌ Нет доступа")
        return

    _, start, end = callback_query.data.split(":")

    keyboard = InlineKeyboardMarkup()

    keyboard.add(
        InlineKeyboardButton(
            "✅ Да",
            callback_data=f"confirmclose:{start}:{end}"
        ),

        InlineKeyboardButton(
            "❌ Нет",
            callback_data="cancelclose"
        )
    )

    await callback_query.message.reply(
        f"⚠️ Закрыть вахту?\n\n"
        f"{start} → {end}",
        reply_markup=keyboard
    )


@dp.callback_query_handler(
    lambda c: c.data.startswith("confirmclose:")
)
async def execute_close_period(
    callback_query: types.CallbackQuery
):

    if not is_admin(callback_query.from_user.id):
        await callback_query.answer("❌ Нет доступа")
        return

    await rotate_tasks()

    await callback_query.message.reply(
        "✅ Вахта закрыта"
    )


@dp.callback_query_handler(
    lambda c: c.data == "cancelclose"
)
async def cancel_close_period(
    callback_query: types.CallbackQuery
):

    await callback_query.message.reply(
        "❌ Закрытие отменено"
    )

@dp.message_handler(commands=['id'])
async def get_id(message: types.Message):

    await message.reply(
        f"Ваш ID: {message.from_user.id}"
    )

@dp.message_handler(commands=['start'])
async def start(message: types.Message):

    role = get_user_role(message.from_user.id)

    if not role:

        await message.reply(
            "⛔ У вас нет доступа"
        )

        return

    await message.reply(
        "🤖 Система задач активна",
        reply_markup=main_menu(message.from_user.id)
    )

# ================= SCHEDULER =================

scheduler.add_job(
    send_pre_report,
    "cron",
    hour=10,
    minute=0
)

# ================= STARTUP =================

async def on_startup(dp):
    scheduler.start()

# ================= RUN =================

if __name__ == "__main__":

    executor.start_polling(
        dp,
        skip_updates=True,
        on_startup=on_startup
    )