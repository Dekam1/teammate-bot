import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, types
from aiogram.contrib.fsm_storage.memory import MemoryStorage
from aiogram.dispatcher import FSMContext
from aiogram.dispatcher.filters.state import State, StatesGroup
from aiogram.types import (
    InlineKeyboardMarkup, InlineKeyboardButton,
    ReplyKeyboardMarkup, KeyboardButton,
    WebAppInfo
)
from dotenv import load_dotenv
from db import Database

load_dotenv()
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBAPP_URL = os.getenv("WEBAPP_URL", "https://your-webapp-url.com")
DATABASE_URL = os.getenv("DATABASE_URL")

bot = Bot(token=BOT_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(bot, storage=storage)
db = Database(DATABASE_URL)

GAMES = {
    "dota2": {"name": "Dota 2", "emoji": "🎮", "ranks": ["Herald","Guardian","Crusader","Archon","Legend","Ancient","Divine","Immortal"], "roles": ["Carry","Midlaner","Offlaner","Soft Support","Hard Support"]},
    "cs2": {"name": "CS2", "emoji": "🔫", "ranks": ["Silver","Gold Nova","MG","DMG","LE","LEM","Supreme","Global"], "roles": ["AWPer","Rifler","Entry Fragger","Support","IGL"]},
    "valorant": {"name": "Valorant", "emoji": "⚡", "ranks": ["Iron","Bronze","Silver","Gold","Platinum","Diamond","Ascendant","Immortal","Radiant"], "roles": ["Duelist","Controller","Sentinel","Initiator"]},
    "mobile_legends": {"name": "Mobile Legends", "emoji": "📱", "ranks": ["Warrior","Elite","Master","Grandmaster","Epic","Legend","Mythic"], "roles": ["Jungler","Gold Lane","Mid","EXP Lane","Roam"]},
    "pubg": {"name": "PUBG Mobile", "emoji": "🪖", "ranks": ["Bronze","Silver","Gold","Platinum","Diamond","Crown","Ace","Conqueror"], "roles": ["Fragger","Sniper","Support","Driver","IGL"]},
    "lol": {"name": "League of Legends", "emoji": "⚔️", "ranks": ["Iron","Bronze","Silver","Gold","Platinum","Emerald","Diamond","Master","Grandmaster","Challenger"], "roles": ["Top","Jungle","Mid","ADC","Support"]},
}

DAILY_LIKES_FREE = 10

class Registration(StatesGroup):
    name = State()
    age = State()
    gender = State()
    seeking = State()
    games = State()
    game_rank = State()
    game_roles = State()
    bio = State()
    avatar = State()

def games_keyboard(selected=None):
    selected = selected or []
    kb = InlineKeyboardMarkup(row_width=2)
    for key, game in GAMES.items():
        mark = "✅ " if key in selected else ""
        kb.insert(InlineKeyboardButton(f"{mark}{game['emoji']} {game['name']}", callback_data=f"game_toggle:{key}"))
    kb.add(InlineKeyboardButton("➡️ Далее", callback_data="games_done"))
    return kb

def gender_keyboard():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton("👦 Парень", callback_data="gender:male"),
           InlineKeyboardButton("👧 Девушка", callback_data="gender:female"),
           InlineKeyboardButton("🌈 Любой", callback_data="gender:any"))
    return kb

def seeking_keyboard():
    kb = InlineKeyboardMarkup(row_width=2)
    kb.add(InlineKeyboardButton("👦 Ищу парня", callback_data="seek:male"),
           InlineKeyboardButton("👧 Ищу девушку", callback_data="seek:female"),
           InlineKeyboardButton("👥 Всех", callback_data="seek:any"))
    return kb

def rank_keyboard(game_key):
    kb = InlineKeyboardMarkup(row_width=1)
    for r in GAMES[game_key]["ranks"]:
        kb.add(InlineKeyboardButton(r, callback_data=f"rank:{r}"))
    kb.add(InlineKeyboardButton("⏭ Пропустить", callback_data="rank:skip"))
    return kb

def roles_keyboard(game_key, selected=None):
    selected = selected or []
    kb = InlineKeyboardMarkup(row_width=1)
    for role in GAMES[game_key]["roles"]:
        mark = "✅ " if role in selected else ""
        kb.add(InlineKeyboardButton(f"{mark}{role}", callback_data=f"role:{role}"))
    kb.add(InlineKeyboardButton("➡️ Далее", callback_data="roles_done"))
    return kb

def main_menu_keyboard():
    kb = ReplyKeyboardMarkup(resize_keyboard=True)
    kb.add(KeyboardButton("🎮 Найти тиммейта", web_app=WebAppInfo(url=WEBAPP_URL)))
    kb.add(KeyboardButton("👤 Моя анкета"), KeyboardButton("⚙️ Настройки"))
    kb.add(KeyboardButton("💎 Премиум"), KeyboardButton("❤️ Мои матчи"))
    return kb

@dp.message_handler(commands=["start"], state="*")
async def cmd_start(message: types.Message, state: FSMContext):
    await state.finish()
    user = await db.get_user(message.from_user.id)
    if user:
        await message.answer(f"С возвращением, {user['name']}! 👋\nНайди себе тиммейта 🎮", reply_markup=main_menu_keyboard())
        return
    await message.answer("👾 Добро пожаловать в <b>TeammateFind</b>!\n\nНайди тиммейта для своей любимой игры.\n\nКак тебя зовут?", parse_mode="HTML")
    await Registration.name.set()

@dp.message_handler(state=Registration.name)
async def reg_name(message: types.Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 2 or len(name) > 30:
        await message.answer("Имя должно быть от 2 до 30 символов:")
        return
    await state.update_data(name=name)
    await message.answer("Сколько тебе лет?")
    await Registration.age.set()

@dp.message_handler(state=Registration.age)
async def reg_age(message: types.Message, state: FSMContext):
    try:
        age = int(message.text.strip())
        if age < 13 or age > 60: raise ValueError
    except ValueError:
        await message.answer("Введи корректный возраст (13–60):")
        return
    await state.update_data(age=age)
    await message.answer("Выбери свой пол:", reply_markup=gender_keyboard())
    await Registration.gender.set()

@dp.callback_query_handler(lambda c: c.data.startswith("gender:"), state=Registration.gender)
async def reg_gender(callback: types.CallbackQuery, state: FSMContext):
    gender = callback.data.split(":")[1]
    labels = {"male": "Парень", "female": "Девушка", "any": "Другой"}
    await state.update_data(gender=gender)
    await callback.message.edit_text(f"Пол: {labels[gender]} ✅\n\nКого ищешь?", reply_markup=seeking_keyboard())
    await Registration.seeking.set()

@dp.callback_query_handler(lambda c: c.data.startswith("seek:"), state=Registration.seeking)
async def reg_seeking(callback: types.CallbackQuery, state: FSMContext):
    seeking = callback.data.split(":")[1]
    await state.update_data(seeking=seeking, selected_games=[])
    await callback.message.edit_text("Выбери игры (можно несколько):", reply_markup=games_keyboard())
    await Registration.games.set()

@dp.callback_query_handler(lambda c: c.data.startswith("game_toggle:"), state=Registration.games)
async def reg_game_toggle(callback: types.CallbackQuery, state: FSMContext):
    game_key = callback.data.split(":")[1]
    data = await state.get_data()
    selected = data.get("selected_games", [])
    if game_key in selected: selected.remove(game_key)
    else: selected.append(game_key)
    await state.update_data(selected_games=selected)
    await callback.message.edit_reply_markup(reply_markup=games_keyboard(selected))

@dp.callback_query_handler(lambda c: c.data == "games_done", state=Registration.games)
async def reg_games_done(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = data.get("selected_games", [])
    if not selected:
        await callback.answer("Выбери хотя бы одну игру!", show_alert=True)
        return
    await state.update_data(games_to_configure=selected.copy(), game_details={})
    await configure_next_game(callback.message, state)

async def configure_next_game(message, state: FSMContext):
    data = await state.get_data()
    games_to_configure = data.get("games_to_configure", [])
    if not games_to_configure:
        await message.edit_text("Расскажи о себе в паре слов (или напиши /skip):")
        await Registration.bio.set()
        return
    current_game = games_to_configure[0]
    game_info = GAMES[current_game]
    await state.update_data(current_game=current_game)
    await message.edit_text(f"{game_info['emoji']} <b>{game_info['name']}</b>\n\nВыбери свой ранг:", parse_mode="HTML", reply_markup=rank_keyboard(current_game))
    await Registration.game_rank.set()

@dp.callback_query_handler(lambda c: c.data.startswith("rank:"), state=Registration.game_rank)
async def reg_rank(callback: types.CallbackQuery, state: FSMContext):
    rank = callback.data.split(":")[1]
    data = await state.get_data()
    current_game = data["current_game"]
    game_details = data.get("game_details", {})
    game_details[current_game] = {"rank": rank if rank != "skip" else None, "roles": []}
    await state.update_data(game_details=game_details, selected_roles=[])
    await callback.message.edit_text(f"Роли в {GAMES[current_game]['name']}:", reply_markup=roles_keyboard(current_game))
    await Registration.game_roles.set()

@dp.callback_query_handler(lambda c: c.data.startswith("role:"), state=Registration.game_roles)
async def reg_role_toggle(callback: types.CallbackQuery, state: FSMContext):
    role = callback.data.split(":")[1]
    data = await state.get_data()
    selected = data.get("selected_roles", [])
    if role in selected: selected.remove(role)
    else: selected.append(role)
    await state.update_data(selected_roles=selected)
    await callback.message.edit_reply_markup(reply_markup=roles_keyboard(data["current_game"], selected))

@dp.callback_query_handler(lambda c: c.data == "roles_done", state=Registration.game_roles)
async def reg_roles_done(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    current_game = data["current_game"]
    game_details = data.get("game_details", {})
    game_details[current_game]["roles"] = data.get("selected_roles", [])
    games_to_configure = data.get("games_to_configure", [])
    games_to_configure.pop(0)
    await state.update_data(game_details=game_details, games_to_configure=games_to_configure)
    await configure_next_game(callback.message, state)

@dp.message_handler(state=Registration.bio)
async def reg_bio(message: types.Message, state: FSMContext):
    bio = None if message.text == "/skip" else message.text[:200]
    await state.update_data(bio=bio)
    await message.answer("Отправь фото для анкеты (или /skip):")
    await Registration.avatar.set()

@dp.message_handler(content_types=types.ContentType.PHOTO, state=Registration.avatar)
async def reg_avatar_photo(message: types.Message, state: FSMContext):
    await state.update_data(avatar_file_id=message.photo[-1].file_id)
    await finish_registration(message, state)

@dp.message_handler(state=Registration.avatar)
async def reg_avatar_skip(message: types.Message, state: FSMContext):
    await state.update_data(avatar_file_id=None)
    await finish_registration(message, state)

async def finish_registration(message: types.Message, state: FSMContext):
    data = await state.get_data()
    user_id = message.from_user.id
    await db.create_user(user_id=user_id, username=message.from_user.username,
        name=data["name"], age=data["age"], gender=data["gender"],
        seeking=data["seeking"], bio=data.get("bio"), avatar_file_id=data.get("avatar_file_id"))
    for game_key, details in data.get("game_details", {}).items():
        await db.add_user_game(user_id=user_id, game=game_key,
            rank=details.get("rank"), roles=details.get("roles", []))
    await state.finish()
    await message.answer(f"🎉 Анкета создана, {data['name']}!\nИщи тиммейтов через кнопку ниже 👇", reply_markup=main_menu_keyboard())

@dp.callback_query_handler(lambda c: c.data.startswith("like:"))
async def handle_like(callback: types.CallbackQuery):
    target_id = int(callback.data.split(":")[1])
    from_id = callback.from_user.id
    user = await db.get_user(from_id)
    if not user["is_premium"] and user["daily_likes"] >= DAILY_LIKES_FREE:
        await callback.answer("❌ Лимит лайков! 💎 Оформи Premium", show_alert=True)
        return
    matched = await db.add_like(from_id, target_id)
    await db.increment_likes(from_id)
    if matched:
        target = await db.get_user(target_id)
        await callback.answer("🎉 Это матч!", show_alert=True)
        try:
            await bot.send_message(target_id, f"🎉 Матч! <b>{user['name']}</b> тоже лайкнул тебя!", parse_mode="HTML")
        except: pass
    else:
        await callback.answer("❤️ Лайк отправлен!")

@dp.message_handler(lambda m: m.text == "👤 Моя анкета")
async def show_my_profile(message: types.Message):
    user = await db.get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала зарегистрируйся! /start")
        return
    games = await db.get_user_games(message.from_user.id)
    games_text = ""
    for g in games:
        info = GAMES.get(g["game"], {})
        roles_str = ", ".join(g["roles"]) if g["roles"] else "—"
        games_text += f"\n{info.get('emoji','🎮')} {info.get('name', g['game'])}: {g['rank'] or '—'} | {roles_str}"
    gender_labels = {"male": "Парень", "female": "Девушка", "any": "Другой"}
    text = (f"👤 <b>{user['name']}</b>, {user['age']} лет\n"
            f"Пол: {gender_labels.get(user['gender'])}\n"
            f"🎮 <b>Игры:</b>{games_text}\n\n"
            f"📝 {user['bio'] or 'Нет описания'}")
    if user["avatar_file_id"]:
        await message.answer_photo(user["avatar_file_id"], caption=text, parse_mode="HTML")
    else:
        await message.answer(text, parse_mode="HTML")

@dp.message_handler(lambda m: m.text == "💎 Премиум")
async def show_premium(message: types.Message):
    kb = InlineKeyboardMarkup()
    kb.add(InlineKeyboardButton("💎 Оформить за 99₽/мес", callback_data="buy_premium"))
    await message.answer(
        "💎 <b>TeammateFind Premium</b>\n\n"
        "✅ Безлимитные лайки\n✅ Кто тебя лайкнул\n✅ Фильтр по рангу\n✅ Буст анкеты\n\n"
        "💰 <b>99₽/месяц</b>", parse_mode="HTML", reply_markup=kb)

@dp.callback_query_handler(lambda c: c.data == "buy_premium")
async def buy_premium(callback: types.CallbackQuery):
    await callback.answer("Напиши @admin для активации!", show_alert=True)

if __name__ == "__main__":
    from aiogram import executor
    async def on_startup(dp):
        await db.connect()
        logger.info("Bot started!")
    executor.start_polling(dp, on_startup=on_startup, skip_updates=True)
