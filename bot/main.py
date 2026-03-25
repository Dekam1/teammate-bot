import asyncio
import logging
import os
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
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
dp = Dispatcher(storage=MemoryStorage())
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
DAILY_LIKES_PREMIUM = 9999
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
class Browse(StatesGroup):
    viewing = State()
class EditProfile(StatesGroup):
    name = State()
    age = State()
    bio = State()
    avatar = State()
    games = State()
    game_rank = State()
    game_roles = State()
def games_keyboard(selected=None):
    selected = selected or []
    buttons = []
    row = []
    for key, game in GAMES.items():
        mark = "✅ " if key in selected else ""
        row.append(InlineKeyboardButton(
            text=f"{mark}{game['emoji']} {game['name']}",
            callback_data=f"game_toggle:{key}"
        ))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)
    buttons.append([InlineKeyboardButton(text="➡️ Далее", callback_data="games_done")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
def gender_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👦 Парень", callback_data="gender:male"),
         InlineKeyboardButton(text="👧 Девушка", callback_data="gender:female")],
        [InlineKeyboardButton(text="🌈 Любой", callback_data="gender:any")]
    ])
def seeking_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="👦 Ищу парня", callback_data="seek:male"),
         InlineKeyboardButton(text="👧 Ищу девушку", callback_data="seek:female")],
        [InlineKeyboardButton(text="👥 Всех", callback_data="seek:any")]
    ])
def rank_keyboard(game_key):
    game = GAMES[game_key]
    buttons = [[InlineKeyboardButton(text=r, callback_data=f"rank:{r}")] for r in game["ranks"]]
    buttons.append([InlineKeyboardButton(text="⏭ Пропустить", callback_data="rank:skip")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
def roles_keyboard(game_key, selected=None):
    selected = selected or []
    game = GAMES[game_key]
    buttons = []
    for role in game["roles"]:
        mark = "✅ " if role in selected else ""
        buttons.append([InlineKeyboardButton(text=f"{mark}{role}", callback_data=f"role:{role}")])
    buttons.append([InlineKeyboardButton(text="➡️ Далее", callback_data="roles_done")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)
def profile_actions_keyboard(target_id, is_premium=False):
    buttons = [
        [InlineKeyboardButton(text="❤️ Лайк", callback_data=f"like:{target_id}"),
         InlineKeyboardButton(text="👎 Пропустить", callback_data=f"skip:{target_id}")],
        [InlineKeyboardButton(text="🚫 Пожаловаться", callback_data=f"report:{target_id}")]
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)
def main_menu_keyboard(webapp_url=None, user_id=None):
    buttons = [
        [KeyboardButton(text="👤 Моя анкета"), KeyboardButton(text="❤️ Мои матчи")],
        [KeyboardButton(text="💎 Премиум"), KeyboardButton(text="⚙️ Настройки")]
    ]
    if webapp_url and user_id:
        buttons.insert(0, [KeyboardButton(
            text="🎮 Найти тиммейта",
            web_app=WebAppInfo(url=f"{webapp_url}?user_id={user_id}")
        )])
    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)
def edit_menu_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Имя", callback_data="edit:name"),
         InlineKeyboardButton(text="🎂 Возраст", callback_data="edit:age")],
        [InlineKeyboardButton(text="📝 О себе", callback_data="edit:bio"),
         InlineKeyboardButton(text="📷 Фото", callback_data="edit:avatar")],
        [InlineKeyboardButton(text="🎮 Игры", callback_data="edit:games")],
        [InlineKeyboardButton(text="🔴 Скрыть анкету", callback_data="toggle_active"),
         InlineKeyboardButton(text="🗑 Удалить анкету", callback_data="delete_profile")],
    ])
@dp.message(CommandStart())
async def cmd_start(message: types.Message, state: FSMContext):
    user = await db.get_user(message.from_user.id)
    if user:
        await message.answer(
            f"С возвращением, {user['name']}! 👋\nНайди себе тиммейта 🎮",
            reply_markup=main_menu_keyboard(WEBAPP_URL, message.from_user.id)
        )
        return
    await message.answer(
        "👾 Добро пожаловать в <b>TeammateFind</b>!\n\n"
        "Найди тиммейта для своей любимой игры.\n\n"
        "Давай создадим твою анкету. Как тебя зовут?",
        parse_mode="HTML"
    )
    await state.set_state(Registration.name)
@dp.message(Registration.name)
async def reg_name(message: types.Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 2 or len(name) > 30:
        await message.answer("Имя должно быть от 2 до 30 символов. Попробуй ещё раз:")
        return
    await state.update_data(name=name)
    await message.answer("Сколько тебе лет?")
    await state.set_state(Registration.age)
@dp.message(Registration.age)
async def reg_age(message: types.Message, state: FSMContext):
    try:
        age = int(message.text.strip())
        if age < 13 or age > 60:
            raise ValueError
    except ValueError:
        await message.answer("Введи корректный возраст (13–60):")
        return
    await state.update_data(age=age)
    await message.answer("Выбери свой пол:", reply_markup=gender_keyboard())
    await state.set_state(Registration.gender)
@dp.callback_query(F.data.startswith("gender:"), Registration.gender)
async def reg_gender(callback: types.CallbackQuery, state: FSMContext):
    gender = callback.data.split(":")[1]
    labels = {"male": "Парень", "female": "Девушка", "any": "Другой"}
    await state.update_data(gender=gender)
    await callback.message.edit_text(
        f"Пол: {labels[gender]} ✅\n\nКого ищешь для игры?",
        reply_markup=seeking_keyboard()
    )
    await state.set_state(Registration.seeking)
@dp.callback_query(F.data.startswith("seek:"), Registration.seeking)
async def reg_seeking(callback: types.CallbackQuery, state: FSMContext):
    seeking = callback.data.split(":")[1]
    await state.update_data(seeking=seeking, selected_games=[])
    await callback.message.edit_text(
        "Выбери игры, в которые ты играешь (можно несколько):",
        reply_markup=games_keyboard()
    )
    await state.set_state(Registration.games)
@dp.callback_query(F.data.startswith("game_toggle:"), Registration.games)
async def reg_game_toggle(callback: types.CallbackQuery, state: FSMContext):
    game_key = callback.data.split(":")[1]
    data = await state.get_data()
    selected = data.get("selected_games", [])
    if game_key in selected:
        selected.remove(game_key)
    else:
        selected.append(game_key)
    await state.update_data(selected_games=selected)
    await callback.message.edit_reply_markup(reply_markup=games_keyboard(selected))
@dp.callback_query(F.data == "games_done", Registration.games)
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
        await message.edit_text("Расскажи о себе в паре слов (или /skip):")
        await state.set_state(Registration.bio)
        return
    current_game = games_to_configure[0]
    game_info = GAMES[current_game]
    await state.update_data(current_game=current_game)
    await message.edit_text(
        f"{game_info['emoji']} <b>{game_info['name']}</b>\n\nВыбери свой ранг:",
        parse_mode="HTML",
        reply_markup=rank_keyboard(current_game)
    )
    await state.set_state(Registration.game_rank)
@dp.callback_query(F.data.startswith("rank:"), Registration.game_rank)
async def reg_rank(callback: types.CallbackQuery, state: FSMContext):
    rank = callback.data.split(":")[1]
    data = await state.get_data()
    current_game = data["current_game"]
    game_details = data.get("game_details", {})
    game_details[current_game] = {"rank": rank if rank != "skip" else None, "roles": []}
    await state.update_data(game_details=game_details, selected_roles=[])
    await callback.message.edit_text(
        f"Какие роли ты предпочитаешь в {GAMES[current_game]['name']}?",
        reply_markup=roles_keyboard(current_game)
    )
    await state.set_state(Registration.game_roles)
@dp.callback_query(F.data.startswith("role:"), Registration.game_roles)
async def reg_role_toggle(callback: types.CallbackQuery, state: FSMContext):
    role = callback.data.split(":")[1]
    data = await state.get_data()
    selected = data.get("selected_roles", [])
    if role in selected:
        selected.remove(role)
    else:
        selected.append(role)
    await state.update_data(selected_roles=selected)
    await callback.message.edit_reply_markup(
        reply_markup=roles_keyboard(data["current_game"], selected)
    )
@dp.callback_query(F.data == "roles_done", Registration.game_roles)
async def reg_roles_done(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    current_game = data["current_game"]
    game_details = data.get("game_details", {})
    game_details[current_game]["roles"] = data.get("selected_roles", [])
    games_to_configure = data.get("games_to_configure", [])
    games_to_configure.pop(0)
    await state.update_data(game_details=game_details, games_to_configure=games_to_configure)
    await configure_next_game(callback.message, state)
@dp.message(Registration.bio)
async def reg_bio(message: types.Message, state: FSMContext):
    bio = None if message.text == "/skip" else message.text[:200]
    await state.update_data(bio=bio)
    await message.answer(
        "Отправь своё фото для анкеты (или /skip):\n"
        "<i>Можно пропустить — будет стандартная аватарка</i>",
        parse_mode="HTML"
    )
    await state.set_state(Registration.avatar)
@dp.message(Registration.avatar, F.photo)
async def reg_avatar_photo(message: types.Message, state: FSMContext):
    file_id = message.photo[-1].file_id
    await state.update_data(avatar_file_id=file_id)
    await finish_registration(message, state)
@dp.message(Registration.avatar)
async def reg_avatar_skip(message: types.Message, state: FSMContext):
    await state.update_data(avatar_file_id=None)
    await finish_registration(message, state)
async def finish_registration(message: types.Message, state: FSMContext):
    data = await state.get_data()
    user_id = message.from_user.id
    await db.create_user(
        user_id=user_id,
        username=message.from_user.username,
        name=data["name"],
        age=data["age"],
        gender=data["gender"],
        seeking=data["seeking"],
        bio=data.get("bio"),
        avatar_file_id=data.get("avatar_file_id")
    )
    for game_key, details in data.get("game_details", {}).items():
        await db.add_user_game(
            user_id=user_id,
            game=game_key,
            rank=details.get("rank"),
            roles=details.get("roles", [])
        )
    await state.clear()
    await message.answer(
        f"🎉 Анкета создана, {data['name']}!\n\n"
        "Теперь ищи тиммейтов через кнопку ниже 👇",
        reply_markup=main_menu_keyboard(WEBAPP_URL, message.from_user.id)
    )
@dp.callback_query(F.data.startswith("like:"))
async def handle_like(callback: types.CallbackQuery):
    target_id = int(callback.data.split(":")[1])
    from_id = callback.from_user.id
    user = await db.get_user(from_id)
    if not user["is_premium"]:
        if user["daily_likes"] >= DAILY_LIKES_FREE:
            await callback.answer(
                "❌ Лимит лайков на сегодня исчерпан!\n💎 Оформи премиум для безлимитных лайков",
                show_alert=True
            )
            return
    matched = await db.add_like(from_id, target_id)
    await db.increment_likes(from_id)
    if matched:
        target = await db.get_user(target_id)
        await callback.answer("🎉 Это матч!", show_alert=True)
        my_username = f"@{callback.from_user.username}" if callback.from_user.username else "нет username"
        target_username = f"@{target['username']}" if target.get('username') else "нет username"
        # Кнопка для текущего пользователя — написать таргету
        if target.get('username'):
            write_url_to_target = f"https://t.me/{target['username']}"
        else:
            write_url_to_target = f"tg://user?id={target['id']}"
        kb_to_target = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=f"✍️ Написать {target['name']}", url=write_url_to_target)
        ]])
        match_text_me = (
            f"🎉 <b>Это матч!</b>\n\n"
            f"👤 <b>{target['name']}</b>, {target['age']} лет\n"
            f"📝 {target.get('bio') or 'Нет описания'}\n\n"
            f"Контакт: {target_username}"
        )
        if target.get('avatar_file_id'):
            await bot.send_photo(callback.from_user.id, target['avatar_file_id'], caption=match_text_me, parse_mode="HTML", reply_markup=kb_to_target)
        else:
            await bot.send_message(callback.from_user.id, match_text_me, parse_mode="HTML", reply_markup=kb_to_target)
        # Кнопка для таргета — написать текущему пользователю
        if callback.from_user.username:
            write_url_to_me = f"https://t.me/{callback.from_user.username}"
        else:
            write_url_to_me = f"tg://user?id={callback.from_user.id}"
        kb_to_me = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text=f"✍️ Написать {user['name']}", url=write_url_to_me)
        ]])
        match_text_target = (
            f"🎉 <b>Это матч!</b>\n\n"
            f"👤 <b>{user['name']}</b>, {user['age']} лет\n"
            f"📝 {user.get('bio') or 'Нет описания'}\n\n"
            f"Контакт: {my_username}"
        )
        try:
            if user.get('avatar_file_id'):
                await bot.send_photo(target_id, user['avatar_file_id'], caption=match_text_target, parse_mode="HTML", reply_markup=kb_to_me)
            else:
                await bot.send_message(target_id, match_text_target, parse_mode="HTML", reply_markup=kb_to_me)
        except Exception:
            pass
    else:
        await callback.answer("❤️ Лайк отправлен!")
@dp.message(F.text == "❤️ Мои матчи")
async def show_matches(message: types.Message):
    user = await db.get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала зарегистрируйся! /start")
        return
    matches = await db.get_matches(message.from_user.id)
    if not matches:
        await message.answer(
            "💔 Матчей пока нет\n\n"
            "Открывай свайп и лайкай игроков — когда кто-то лайкнет тебя в ответ, появится матч!"
        )
        return
    await message.answer(f"❤️ <b>Твои матчи ({len(matches)}):</b>", parse_mode="HTML")
    for m in matches:
        games = await db.get_user_games(m['id'])
        games_text = " ".join([GAMES.get(g['game'], {}).get('emoji', '🎮') + " " + GAMES.get(g['game'], {}).get('name', g['game']) for g in games])
        username_str = f"@{m['username']}" if m.get('username') else "нет username"
        text = (
            f"👤 <b>{m['name']}</b>, {m['age']} лет\n"
            f"🎮 {games_text}\n"
            f"📝 {m.get('bio') or 'Нет описания'}\n"
            f"Контакт: {username_str}"
        )
        # Кнопка всегда есть — с username или через tg://user?id=
        if m.get('username'):
            write_url = f"https://t.me/{m['username']}"
        else:
            write_url = f"tg://user?id={m['id']}"
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="✍️ Написать", url=write_url)
        ]])
        if m.get('avatar_file_id'):
            await message.answer_photo(m['avatar_file_id'], caption=text, parse_mode="HTML", reply_markup=kb)
        else:
            await message.answer(text, parse_mode="HTML", reply_markup=kb)
@dp.callback_query(F.data.startswith("skip:"))
async def handle_skip(callback: types.CallbackQuery):
    await callback.answer("👎 Пропущено")
@dp.message(F.text == "👤 Моя анкета")
async def show_my_profile(message: types.Message):
    user = await db.get_user(message.from_user.id)
    if not user:
        await message.answer("Сначала зарегистрируйся! /start")
        return
    games = await db.get_user_games(message.from_user.id)
    games_text = ""
    for g in games:
        game_info = GAMES.get(g["game"], {})
        roles_str = ", ".join(g["roles"]) if g["roles"] else "—"
        rank_str = g["rank"] or "—"
        games_text += f"\n{game_info.get('emoji','🎮')} {game_info.get('name', g['game'])}: {rank_str} | {roles_str}"
    gender_labels = {"male": "Парень", "female": "Девушка", "any": "Другой"}
    seek_labels = {"male": "Парней", "female": "Девушек", "any": "Всех"}
    premium_str = "💎 Премиум" if user["is_premium"] else "Бесплатный"
    text = (
        f"👤 <b>{user['name']}</b>, {user['age']} лет\n"
        f"Пол: {gender_labels.get(user['gender'], user['gender'])}\n"
        f"Ищет: {seek_labels.get(user['seeking'], user['seeking'])}\n"
        f"Статус: {premium_str}\n\n"
        f"🎮 <b>Игры:</b>{games_text}\n\n"
        f"📝 {user['bio'] or 'Нет описания'}"
    )
    edit_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✏️ Редактировать", callback_data="edit_profile")],
        [InlineKeyboardButton(text="🔴 Скрыть анкету", callback_data="toggle_active")]
    ])
    if user["avatar_file_id"]:
        await message.answer_photo(user["avatar_file_id"], caption=text, parse_mode="HTML", reply_markup=edit_kb)
    else:
        await message.answer(text, parse_mode="HTML", reply_markup=edit_kb)
@dp.message(F.text == "💎 Премиум")
async def show_premium(message: types.Message):
    text = (
        "💎 <b>TeammateFind Premium</b>\n\n"
        "✅ Безлимитные лайки (бесплатно: 10/день)\n"
        "✅ Видеть кто тебя лайкнул\n"
        "✅ Фильтр по рангу\n"
        "✅ Буст анкеты (показывается первым)\n"
        "✅ Значок Premium на анкете\n\n"
        "💰 Стоимость: <b>99₽/месяц</b>"
    )
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Оформить за 99₽/мес", callback_data="buy_premium")]
    ])
    await message.answer(text, parse_mode="HTML", reply_markup=kb)
@dp.callback_query(F.data == "buy_premium")
async def buy_premium(callback: types.CallbackQuery):
    await callback.answer(
        "Оплата будет добавлена в следующем обновлении!\n"
        "Напиши @admin для ручной активации.",
        show_alert=True
    )
@dp.callback_query(F.data == "edit_profile")
async def edit_profile_menu(callback: types.CallbackQuery):
    await callback.message.edit_reply_markup(reply_markup=edit_menu_keyboard())
    await callback.answer()
@dp.callback_query(F.data.startswith("edit:"))
async def edit_field(callback: types.CallbackQuery, state: FSMContext):
    field = callback.data.split(":")[1]
    prompts = {
        "name": "✏️ Введи новое имя:",
        "age": "🎂 Введи новый возраст:",
        "bio": "📝 Напиши новое описание (или /skip чтобы убрать):",
        "avatar": "📷 Отправь новое фото (или /skip чтобы убрать):",
        "games": "🎮 Выбери игры:"
    }
    if field == "games":
        user_games = await db.get_user_games(callback.from_user.id)
        selected = [g["game"] for g in user_games]
        await state.update_data(selected_games=selected)
        await callback.message.answer(prompts[field], reply_markup=games_keyboard(selected))
        await state.set_state(EditProfile.games)
    elif field == "avatar":
        await callback.message.answer(prompts[field])
        await state.set_state(EditProfile.avatar)
    else:
        await callback.message.answer(prompts[field])
        await state.set_state(getattr(EditProfile, field))
    await callback.answer()
@dp.message(EditProfile.name)
async def edit_name(message: types.Message, state: FSMContext):
    name = message.text.strip()
    if len(name) < 2 or len(name) > 30:
        await message.answer("Имя должно быть от 2 до 30 символов:")
        return
    await db.update_user_field(message.from_user.id, "name", name)
    await state.clear()
    await message.answer(f"✅ Имя изменено на {name}!")
    await show_my_profile(message)
@dp.message(EditProfile.age)
async def edit_age(message: types.Message, state: FSMContext):
    try:
        age = int(message.text.strip())
        if age < 13 or age > 60:
            raise ValueError
    except ValueError:
        await message.answer("Введи корректный возраст (13–60):")
        return
    await db.update_user_field(message.from_user.id, "age", age)
    await state.clear()
    await message.answer(f"✅ Возраст изменён на {age}!")
    await show_my_profile(message)
@dp.message(EditProfile.bio)
async def edit_bio(message: types.Message, state: FSMContext):
    bio = None if message.text == "/skip" else message.text[:200]
    await db.update_user_field(message.from_user.id, "bio", bio)
    await state.clear()
    await message.answer("✅ Описание обновлено!")
    await show_my_profile(message)
@dp.message(EditProfile.avatar, F.photo)
async def edit_avatar_photo(message: types.Message, state: FSMContext):
    file_id = message.photo[-1].file_id
    await db.update_user_field(message.from_user.id, "avatar_file_id", file_id)
    await state.clear()
    await message.answer("✅ Фото обновлено!")
    await show_my_profile(message)
@dp.message(EditProfile.avatar)
async def edit_avatar_skip(message: types.Message, state: FSMContext):
    if message.text == "/skip":
        await db.update_user_field(message.from_user.id, "avatar_file_id", None)
        await state.clear()
        await message.answer("✅ Фото удалено!")
        await show_my_profile(message)
    else:
        await message.answer("Отправь фото или /skip:")
@dp.callback_query(F.data.startswith("game_toggle:"), EditProfile.games)
async def edit_game_toggle(callback: types.CallbackQuery, state: FSMContext):
    game_key = callback.data.split(":")[1]
    data = await state.get_data()
    selected = data.get("selected_games", [])
    if game_key in selected:
        selected.remove(game_key)
    else:
        selected.append(game_key)
    await state.update_data(selected_games=selected)
    await callback.message.edit_reply_markup(reply_markup=games_keyboard(selected))
@dp.callback_query(F.data == "games_done", EditProfile.games)
async def edit_games_done(callback: types.CallbackQuery, state: FSMContext):
    data = await state.get_data()
    selected = data.get("selected_games", [])
    if not selected:
        await callback.answer("Выбери хотя бы одну игру!", show_alert=True)
        return
    await db.delete_user_games(callback.from_user.id)
    await state.update_data(games_to_configure=selected.copy(), game_details={})
    await configure_next_game(callback.message, state)
@dp.callback_query(F.data == "toggle_active")
async def toggle_profile_active(callback: types.CallbackQuery):
    await db.toggle_active(callback.from_user.id)
    user = await db.get_user(callback.from_user.id)
    status = "скрыта" if not user["is_active"] else "активна"
    await callback.answer(f"Анкета {status}!", show_alert=True)
@dp.callback_query(F.data == "delete_profile")
async def delete_profile_confirm(callback: types.CallbackQuery):
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="✅ Да, удалить", callback_data="delete_confirmed"),
         InlineKeyboardButton(text="❌ Отмена", callback_data="edit_profile")]
    ])
    await callback.message.edit_reply_markup(reply_markup=kb)
    await callback.answer()
@dp.callback_query(F.data == "delete_confirmed")
async def delete_profile_confirmed(callback: types.CallbackQuery):
    await db.delete_user(callback.from_user.id)
    await callback.message.answer("Анкета удалена. Напиши /start чтобы создать новую.")
    await callback.answer()
async def main():
    await db.connect()
    await dp.start_polling(bot)
if __name__ == "__main__":
    asyncio.run(main())
