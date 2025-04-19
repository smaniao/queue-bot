import asyncio
import sqlite3
import pandas as pd
import os
from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.context import FSMContext
from aiogram.types import Message, ReplyKeyboardMarkup, KeyboardButton
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, CallbackQuery
from openpyxl import Workbook
from datetime import datetime, timezone, timedelta

TOKEN = "7561845004:AAF04nNPTsyUI14AEIC8_p_0LifQK4sUHjM"
ADMIN_ID = 658900699

bot = Bot(token=TOKEN)
dp = Dispatcher()

conn = sqlite3.connect("queue.db")
cursor = conn.cursor()
cursor.execute("""
CREATE TABLE IF NOT EXISTS queue (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER,
    username TEXT,
    car_number TEXT,
    destination TEXT,
    registration_time TIMESTAMP,
    load_time TIMESTAMP
)
""")
conn.commit()

cursor.execute("""
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    car_number TEXT,
    destination TEXT,
    registration_time TIMESTAMP,
    load_time TIMESTAMP
)
""")
conn.commit()

class JoinQueueState(StatesGroup):
    car_number = State()
    destination = State()

destinations = ["Астана", "Алматы", "Шымкент", "Кызылорда", "Туркестан", "Сарыагаш", "Жетисай"]
destination_keyboard = ReplyKeyboardMarkup(
    keyboard=[[KeyboardButton(text=city)] for city in destinations],
    resize_keyboard=True,
    one_time_keyboard=True
)

@dp.message(Command("start"))
async def start(message: Message):
    await message.answer("Привет! Используй /join, чтобы встать в очередь.")

@dp.message(Command("join"))
async def join_queue(message: Message, state: FSMContext):
    await message.answer("Введите номер вашего автотранспорта:")
    await state.set_state(JoinQueueState.car_number)

@dp.message(JoinQueueState.car_number)
async def enter_car_number(message: Message, state: FSMContext):
    await state.update_data(car_number=message.text)
    await message.answer("Выберите направление:", reply_markup=destination_keyboard)
    await state.set_state(JoinQueueState.destination)

@dp.message(JoinQueueState.destination)
async def enter_destination(message: Message, state: FSMContext):
    if message.text not in destinations:
        await message.answer("Пожалуйста, выберите направление из списка.")
        return

    user_data = await state.get_data()
    user_id = message.from_user.id
    username = message.from_user.username
    car_number = user_data["car_number"]
    destination = message.text
    local_time = datetime.now(timezone(timedelta(hours=6)))

    cursor.execute("INSERT INTO queue (user_id, username, car_number, destination, registration_time) VALUES (?, ?, ?, ?, ?)", 
                   (user_id, username, car_number, destination, local_time))
    conn.commit()

    cursor.execute("SELECT COUNT(*) FROM queue WHERE id < (SELECT id FROM queue WHERE user_id = ?)", (user_id,))
    position = cursor.fetchone()[0]

    await message.answer(
        f"Вы добавлены в очередь!\n"
        f"\U0001F69B Номер: {car_number}\n"
        f"\U0001F4CD Направление: {destination}\n"
        f"\U0001F697 Перед вами {position} машин(ы)."
    )
    await state.clear()

@dp.message(Command("queue"))
async def show_queue(message: Message):
    cursor.execute("SELECT car_number, destination FROM queue")
    users = cursor.fetchall()

    if users:
        queue_list = "\n".join([f"{i+1}. \U0001F69B {user[0]} \u279E {user[1]}" for i, user in enumerate(users)])
        await message.answer(f"\U0001F697 Очередь:\n{queue_list}")
    else:
        await message.answer("Очередь пуста!")

@dp.message(Command("leave"))
async def leave_queue(message: Message):
    user_id = message.from_user.id
    cursor.execute("DELETE FROM queue WHERE user_id = ?", (user_id,))
    conn.commit()
    await message.answer("Вы вышли из очереди.")

@dp.message(Command("next"))
async def next_user(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("У вас нет прав использовать эту команду.")
        return

    cursor.execute("SELECT id, user_id, username, car_number, destination FROM queue ORDER BY id ASC LIMIT 1")
    first_user = cursor.fetchone()

    if first_user:
        queue_id, user_id, username, car_number, destination = first_user
        load_time = datetime.now(timezone(timedelta(hours=6)))
        cursor.execute("UPDATE queue SET load_time = ? WHERE id = ?", (load_time, queue_id))
        conn.commit()

        cursor.execute("""
        INSERT INTO history (car_number, destination, registration_time, load_time)
        SELECT car_number, destination, registration_time, load_time FROM queue WHERE id = ?
        """, (queue_id,))
        conn.commit()

        cursor.execute("DELETE FROM queue WHERE id = ?", (queue_id,))
        conn.commit()

        try:
            await bot.send_message(user_id, "\U0001F69B Ваша очередь подошла! Вы можете ехать на погрузку.")
        except Exception:
            await message.answer(f"⚠️ Не удалось отправить сообщение пользователю @{username}.")

        cursor.execute("SELECT car_number, destination FROM queue ORDER BY id ASC LIMIT 1")
        next_user = cursor.fetchone()

        if next_user:
            await message.answer(
                f"✅ @{username} ({car_number} ➡️ {destination}) отправлен на погрузку.\n"
                f"🔜 Следующий: 🚛 {next_user[0]} ➡️ {next_user[1]}"
            )
        else:
            await message.answer(f"✅ @{username} ({car_number} ➡️ {destination}) отправлен на погрузку.\nОчередь пуста.")
    else:
        await message.answer("⚠️ Очередь уже пуста!")

@dp.message(Command("prioritize"))
async def prioritize_command(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("У вас нет прав использовать эту команду.")
        return

    cursor.execute("SELECT id, car_number, destination FROM queue ORDER BY id ASC")
    cars = cursor.fetchall()

    if not cars:
        await message.answer("Очередь пуста.")
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{car[1]} ➡️ {car[2]}", callback_data=f"prioritize_{car[0]}")]
        for car in cars
    ])

    await message.answer("Выберите машину для приоритизации:", reply_markup=keyboard)

@dp.callback_query(lambda c: c.data.startswith("prioritize_"))
async def handle_prioritize_callback(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("У вас нет прав.", show_alert=True)
        return

    car_id = int(callback.data.split("_")[1])
    cursor.execute("SELECT MIN(id) FROM queue")
    min_id = cursor.fetchone()[0] or 0

    cursor.execute("UPDATE queue SET id = ? WHERE id = ?", (min_id - 1, car_id))
    conn.commit()

    await callback.message.edit_text("✅ Машина приоритизирована и теперь первая в очереди.")

@dp.message(Command("export"))
async def export_queue(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("У вас нет прав использовать эту команду.")
        return

    cursor.execute("SELECT car_number, destination, registration_time, load_time FROM history ORDER BY id ASC")
    data = cursor.fetchall()

    if not data:
        await message.answer("📭 Сегодня никто не проходил через очередь.")
        return

    wb = Workbook()
    ws = wb.active
    ws.append(["Номер машины", "Направление", "Время регистрации", "Время заезда на погрузку"])

    for row in data:
        ws.append(row)

    today = datetime.now(timezone(timedelta(hours=6))).date().strftime("%Y-%m-%d")
    filename = f"report_{today}.xlsx"
    wb.save(filename)

    await bot.send_document(message.chat.id, types.FSInputFile(filename), caption=f"📊 Отчёт за {today}")

@dp.message(Command("clear"))
async def clear_queue(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("У вас нет прав использовать эту команду.")
        return

    cursor.execute("DELETE FROM queue")
    conn.commit()
    await message.answer("Очередь полностью очищена.")

async def main():
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())