import asyncio
import os
import random
from datetime import datetime
from collections import defaultdict

import openpyxl
from openpyxl import Workbook
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton, FSInputFile,
    ReplyKeyboardMarkup, KeyboardButton,
)

# ---------- Настройки ----------
load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID = int(os.getenv("ADMIN_ID", "0"))  # ваш Telegram ID, задаётся в .env

bot = Bot(token=TOKEN)
dp = Dispatcher()

QUESTIONS_FILE = "questions.xlsx"
RESULTS_FILE = "results.xlsx"
QUESTIONS_PER_TEST = 15


# =====================================================================
# ЗАГРУЗКА ВОПРОСОВ
# =====================================================================
def load_questions():
    wb = openpyxl.load_workbook(QUESTIONS_FILE)
    ws = wb.active
    questions = []
    for row in ws.iter_rows(min_row=2, values_only=True):
        category, question, opt1, opt2, opt3, opt4, correct = row
        if not question:
            continue
        questions.append({
            "category": category,
            "question": question,
            "options": [opt1, opt2, opt3, opt4],
            "correct": int(correct),
        })
    return questions


ALL_QUESTIONS = load_questions()
CATEGORIES = sorted(set(q["category"] for q in ALL_QUESTIONS))

user_sessions = {}


# =====================================================================
# РАБОТА С ФАЙЛОМ РЕЗУЛЬТАТОВ
# =====================================================================
RESULTS_HEADERS = ["Дата и время", "User ID", "Имя", "Username", "Раздел", "Правильных", "Всего", "Процент"]


def ensure_results_file():
    if not os.path.exists(RESULTS_FILE):
        wb = Workbook()
        ws = wb.active
        ws.append(RESULTS_HEADERS)
        wb.save(RESULTS_FILE)


def save_result(user, category, score, total):
    ensure_results_file()
    wb = openpyxl.load_workbook(RESULTS_FILE)
    ws = wb.active
    percent = round(score / total * 100)
    ws.append([
        datetime.now().strftime("%d.%m.%Y %H:%M"),
        user.id,
        user.full_name,
        f"@{user.username}" if user.username else "-",
        category,
        score,
        total,
        percent,
    ])
    wb.save(RESULTS_FILE)


def read_all_results():
    ensure_results_file()
    wb = openpyxl.load_workbook(RESULTS_FILE)
    ws = wb.active
    rows = list(ws.iter_rows(min_row=2, values_only=True))
    return rows


# =====================================================================
# КЛАВИАТУРЫ
# =====================================================================
def main_menu_keyboard(is_admin: bool):
    buttons = [
        [InlineKeyboardButton(text="📝 Пройти тест", callback_data="menu:test")],
        [InlineKeyboardButton(text="📊 Мои результаты", callback_data="menu:my_results")],
    ]
    if is_admin:
        buttons.append([InlineKeyboardButton(text="⚙️ Админ-панель", callback_data="menu:admin")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def categories_keyboard():
    buttons = [[InlineKeyboardButton(text=cat, callback_data=f"start_test:{cat}")] for cat in CATEGORIES]
    buttons.append([InlineKeyboardButton(text="⬅️ Назад", callback_data="menu:home")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def back_to_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="menu:home")]
    ])


def admin_menu_keyboard():
    buttons = [
        [InlineKeyboardButton(text="📈 Общая статистика", callback_data="admin:stats")],
        [InlineKeyboardButton(text="📉 Слабые результаты (<60%)", callback_data="admin:weak")],
        [InlineKeyboardButton(text="📥 Скачать файл результатов", callback_data="admin:download")],
        [InlineKeyboardButton(text="⬅️ В главное меню", callback_data="menu:home")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def persistent_keyboard(is_admin_user: bool):
    """Кнопки, которые всегда видны внизу экрана, не нужно листать чат"""
    buttons = [
        [KeyboardButton(text="📝 Пройти тест"), KeyboardButton(text="📊 Мои результаты")],
    ]
    if is_admin_user:
        buttons.append([KeyboardButton(text="⚙️ Админ-панель")])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True, is_persistent=True)


# =====================================================================
# ГЛАВНОЕ МЕНЮ
# =====================================================================
async def show_main_menu(chat_id, message_id=None, user_id=None):
    is_admin = (user_id == ADMIN_ID)
    text = (
        "👋 Привет! Я бот для тестирования официантов по меню и алкоголю.\n\n"
        "Выбери, что хочешь сделать:"
    )
    kb = main_menu_keyboard(is_admin)
    if message_id:
        await bot.edit_message_text(text, chat_id=chat_id, message_id=message_id, reply_markup=kb)
    else:
        await bot.send_message(chat_id, text, reply_markup=kb)


@dp.message(CommandStart())
async def start_handler(message: types.Message):
    is_adm = (message.from_user.id == ADMIN_ID)
    await message.answer("Меню открыто снизу 👇", reply_markup=persistent_keyboard(is_adm))
    await show_main_menu(message.chat.id, user_id=message.from_user.id)


@dp.message(F.text == "📝 Пройти тест")
async def kb_test(message: types.Message):
    await message.answer("Выбери раздел для теста:", reply_markup=categories_keyboard())


@dp.message(F.text == "📊 Мои результаты")
async def kb_my_results(message: types.Message):
    all_results = read_all_results()
    my_results = [r for r in all_results if r[1] == message.from_user.id]
    if not my_results:
        text = "У тебя пока нет пройденных тестов.\nНажми «Пройти тест», чтобы начать!"
    else:
        my_results = my_results[-10:]
        lines = ["📊 Твои последние результаты:\n"]
        for r in reversed(my_results):
            date, _, _, _, category, score, total, percent = r
            lines.append(f"{date} — {category}: {score}/{total} ({percent}%)")
        text = "\n".join(lines)
    await message.answer(text)


@dp.message(F.text == "⚙️ Админ-панель")
async def kb_admin(message: types.Message):
    if message.from_user.id != ADMIN_ID:
        return
    await message.answer("⚙️ Админ-панель", reply_markup=admin_menu_keyboard())


@dp.message(Command("test"))
async def test_command(message: types.Message):
    await message.answer("Выбери раздел для теста:", reply_markup=categories_keyboard())


@dp.callback_query(F.data == "menu:home")
async def menu_home(callback: types.CallbackQuery):
    await show_main_menu(callback.message.chat.id, message_id=callback.message.message_id, user_id=callback.from_user.id)
    await callback.answer()


@dp.callback_query(F.data == "menu:test")
async def menu_test(callback: types.CallbackQuery):
    await callback.message.edit_text("Выбери раздел для теста:", reply_markup=categories_keyboard())
    await callback.answer()


# =====================================================================
# МОИ РЕЗУЛЬТАТЫ (для официанта)
# =====================================================================
@dp.callback_query(F.data == "menu:my_results")
async def menu_my_results(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    all_results = read_all_results()
    my_results = [r for r in all_results if r[1] == user_id]

    if not my_results:
        text = "У тебя пока нет пройденных тестов.\nНажми «Пройти тест», чтобы начать!"
    else:
        my_results = my_results[-10:]
        lines = ["📊 Твои последние результаты:\n"]
        for r in reversed(my_results):
            date, _, _, _, category, score, total, percent = r
            lines.append(f"{date} — {category}: {score}/{total} ({percent}%)")
        text = "\n".join(lines)

    await callback.message.edit_text(text, reply_markup=back_to_menu_keyboard())
    await callback.answer()


# =====================================================================
# ПРОХОЖДЕНИЕ ТЕСТА
# =====================================================================
@dp.callback_query(F.data.startswith("start_test:"))
async def start_test(callback: types.CallbackQuery):
    category = callback.data.split(":", 1)[1]
    pool = [q for q in ALL_QUESTIONS if q["category"] == category]
    random.shuffle(pool)
    selected = pool[:QUESTIONS_PER_TEST]

    user_sessions[callback.from_user.id] = {
        "questions": selected,
        "index": 0,
        "score": 0,
        "category": category,
        "chat_id": callback.message.chat.id,
        "message_id": callback.message.message_id,
    }
    await send_question(callback.from_user.id)
    await callback.answer()


async def send_question(user_id):
    session = user_sessions[user_id]
    index = session["index"]
    question = session["questions"][index]

    buttons = []
    for i, option in enumerate(question["options"], start=1):
        buttons.append([InlineKeyboardButton(text=str(option), callback_data=f"answer:{i}")])
    keyboard = InlineKeyboardMarkup(inline_keyboard=buttons)

    progress = "🟩" * index + "⬜️" * (len(session["questions"]) - index)
    text = f"{progress}\nВопрос {index + 1} из {len(session['questions'])}:\n\n{question['question']}"

    await bot.edit_message_text(
        text, chat_id=session["chat_id"], message_id=session["message_id"], reply_markup=keyboard
    )


@dp.callback_query(F.data.startswith("answer:"))
async def answer_handler(callback: types.CallbackQuery):
    user_id = callback.from_user.id
    if user_id not in user_sessions:
        await callback.answer("Тест не найден. Напиши /start, чтобы начать заново.")
        return

    session = user_sessions[user_id]
    chosen = int(callback.data.split(":", 1)[1])
    question = session["questions"][session["index"]]

    if chosen == question["correct"]:
        session["score"] += 1
        result_text = "✅ Верно!"
    else:
        correct_option = question["options"][question["correct"] - 1]
        result_text = f"❌ Неверно. Правильный ответ: {correct_option}"

    await callback.answer(result_text, show_alert=False)

    session["index"] += 1

    if session["index"] < len(session["questions"]):
        await send_question(user_id)
    else:
        score = session["score"]
        total = len(session["questions"])
        category = session["category"]
        percent = round(score / total * 100)

        if percent >= 80:
            comment = "Отличный результат! 🎉"
        elif percent >= 50:
            comment = "Неплохо, но есть куда расти 💪"
        else:
            comment = "Стоит повторить материал 📖"

        text = (
            f"Тест завершён!\n\n"
            f"Раздел: {category}\n"
            f"Правильных ответов: {score} из {total} ({percent}%)\n\n"
            f"{comment}"
        )
        await bot.edit_message_text(
            text, chat_id=session["chat_id"], message_id=session["message_id"],
            reply_markup=back_to_menu_keyboard()
        )
        save_result(callback.from_user, category, score, total)
        del user_sessions[user_id]


# =====================================================================
# АДМИН-ПАНЕЛЬ
# =====================================================================
def is_admin(user_id):
    return ADMIN_ID != 0 and user_id == ADMIN_ID


@dp.callback_query(F.data == "menu:admin")
async def menu_admin(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ только для администратора.", show_alert=True)
        return
    await callback.message.edit_text("⚙️ Админ-панель", reply_markup=admin_menu_keyboard())
    await callback.answer()


@dp.callback_query(F.data == "admin:stats")
async def admin_stats(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ только для администратора.", show_alert=True)
        return

    results = read_all_results()
    if not results:
        text = "Пока нет ни одного пройденного теста."
    else:
        total_tests = len(results)
        avg_percent = round(sum(r[7] for r in results) / total_tests)

        by_category = defaultdict(list)
        for r in results:
            by_category[r[4]].append(r[7])

        unique_users = len({r[1] for r in results})

        lines = [
            "📈 Общая статистика\n",
            f"Всего пройдено тестов: {total_tests}",
            f"Уникальных официантов: {unique_users}",
            f"Средний результат: {avg_percent}%\n",
            "По разделам:",
        ]
        for cat, percents in sorted(by_category.items()):
            avg = round(sum(percents) / len(percents))
            lines.append(f"  {cat}: {avg}% (тестов: {len(percents)})")

        text = "\n".join(lines)

    await callback.message.edit_text(text, reply_markup=admin_menu_keyboard())
    await callback.answer()


@dp.callback_query(F.data == "admin:weak")
async def admin_weak(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ только для администратора.", show_alert=True)
        return

    results = read_all_results()
    weak = [r for r in results if r[7] < 60]
    weak = sorted(weak, key=lambda r: r[7])[:15]

    if not weak:
        text = "Слабых результатов (ниже 60%) не найдено. 👍"
    else:
        lines = ["📉 Слабые результаты (ниже 60%):\n"]
        for r in weak:
            date, _, name, username, category, score, total, percent = r
            lines.append(f"{date} — {name} ({username}) — {category}: {score}/{total} ({percent}%)")
        text = "\n".join(lines)

    await callback.message.edit_text(text, reply_markup=admin_menu_keyboard())
    await callback.answer()


@dp.callback_query(F.data == "admin:download")
async def admin_download(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.id):
        await callback.answer("Доступ только для администратора.", show_alert=True)
        return

    ensure_results_file()
    if os.path.exists(RESULTS_FILE):
        await bot.send_document(callback.message.chat.id, FSInputFile(RESULTS_FILE))
    await callback.answer()


# =====================================================================
# ЗАПУСК
# =====================================================================
async def main():
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())