from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response
from pydantic import BaseModel
import asyncpg
import os
import httpx
from dotenv import load_dotenv

load_dotenv()
app = FastAPI()

DATABASE_URL = os.getenv("DATABASE_URL")
BOT_TOKEN = os.getenv("BOT_TOKEN")

# ─────────────────────── DB helpers ───────────────────────

async def get_pool() -> asyncpg.Pool:
    """Возвращает пул соединений, создаёт его при первом вызове."""
    if not hasattr(app.state, "pool") or app.state.pool is None:
        app.state.pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)
    return app.state.pool


@app.on_event("startup")
async def startup():
    app.state.pool = await asyncpg.create_pool(DATABASE_URL, min_size=2, max_size=10)


@app.on_event("shutdown")
async def shutdown():
    if hasattr(app.state, "pool") and app.state.pool:
        await app.state.pool.close()


async def fetch_user(pool: asyncpg.Pool, user_id: int) -> dict | None:
    row = await pool.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
    return dict(row) if row else None


async def fetch_user_games_text(pool: asyncpg.Pool, user_id: int) -> str:
    GAMES = {
        "dota2": "🎮 Dota 2", "cs2": "🔫 CS2", "valorant": "⚡ Valorant",
        "mobile_legends": "📱 Mobile Legends", "pubg": "🪖 PUBG", "lol": "⚔️ LoL"
    }
    rows = await pool.fetch(
        "SELECT game, rank, roles FROM user_games WHERE user_id = $1", user_id
    )
    parts = []
    for r in rows:
        name = GAMES.get(r["game"], r["game"])
        rank = f" · {r['rank']}" if r.get("rank") else ""
        roles_list = r.get("roles") or []
        roles = f" ({', '.join(roles_list)})" if roles_list else ""
        parts.append(f"{name}{rank}{roles}")
    return "\n".join(parts) if parts else "Не указаны"


# ─────────────────────── Notifications ───────────────────────

def _build_write_url(user: dict) -> str:
    """Формирует ссылку для написания пользователю."""
    if user.get("username"):
        return f"https://t.me/{user['username']}"
    return f"tg://user?id={user['id']}"


async def _send_tg(client: httpx.AsyncClient, method: str, payload: dict):
    try:
        await client.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",
            json=payload,
            timeout=10,
        )
    except Exception as e:
        print(f"[TG] Error sending {method}: {e}")


async def notify_match(client: httpx.AsyncClient, pool: asyncpg.Pool,
                       sender_id: int, receiver: dict):
    """Уведомление об успешном матче."""
    games_text = await fetch_user_games_text(pool, receiver["id"])
    gender_labels = {"male": "Парень", "female": "Девушка", "any": "–"}
    gender = gender_labels.get(receiver.get("gender", ""), "–")

    text = (
        f"🎉 *Это матч!*\n\n"
        f"👤 *{receiver['name']}*, {receiver['age']} лет · {gender}\n"
        f"📝 {receiver.get('bio') or 'Нет описания'}\n\n"
        f"🎮 *Игры:*\n{games_text}"
    )
    write_url = _build_write_url(receiver)
    reply_markup = {
        "inline_keyboard": [[{
            "text": f"✍️ Написать {receiver['name']}",
            "url": write_url
        }]]
    }

    if receiver.get("avatar_file_id"):
        await _send_tg(client, "sendPhoto", {
            "chat_id": sender_id,
            "photo": receiver["avatar_file_id"],
            "caption": text,
            "parse_mode": "Markdown",
            "reply_markup": reply_markup,
        })
    else:
        await _send_tg(client, "sendMessage", {
            "chat_id": sender_id,
            "text": text,
            "parse_mode": "Markdown",
            "reply_markup": reply_markup,
        })


async def send_match_notifications(pool: asyncpg.Pool, user1: dict, user2: dict):
    if not BOT_TOKEN:
        return
    async with httpx.AsyncClient() as client:
        await notify_match(client, pool, user1["id"], user2)
        await notify_match(client, pool, user2["id"], user1)


async def send_liked_notification(pool: asyncpg.Pool, liker: dict,
                                  target_id: int, target_is_premium: bool):
    """Уведомление о том, что тебя лайкнули."""
    if not BOT_TOKEN:
        return
    async with httpx.AsyncClient() as client:
        if target_is_premium:
            write_url = _build_write_url(liker)
            text = (
                f"❤️ *Тебя лайкнул {liker['name']}!*\n\n"
                f"👤 {liker['name']}, {liker['age']} лет\n"
                f"📝 {liker.get('bio') or 'Нет описания'}\n\n"
                f"Открой свайп и лайкни в ответ!"
            )
            reply_markup = {"inline_keyboard": [[{
                "text": f"✍️ Написать {liker['name']}",
                "url": write_url,
            }]]}
            if liker.get("avatar_file_id"):
                await _send_tg(client, "sendPhoto", {
                    "chat_id": target_id,
                    "photo": liker["avatar_file_id"],
                    "caption": text,
                    "parse_mode": "Markdown",
                    "reply_markup": reply_markup,
                })
            else:
                await _send_tg(client, "sendMessage", {
                    "chat_id": target_id,
                    "text": text,
                    "parse_mode": "Markdown",
                    "reply_markup": reply_markup,
                })
        else:
            # Без Premium — анонимное уведомление.
            # Кнопка ведёт на deep-link для покупки Premium через бот.
            await _send_tg(client, "sendMessage", {
                "chat_id": target_id,
                "text": (
                    "❤️ Кто-то лайкнул твою анкету!\n\n"
                    "Открой свайп и найди своего тиммейта 🎮"
                ),
                "reply_markup": {
                    "inline_keyboard": [[{
                        "text": "💎 Узнать кто (Premium)",
                        # deep-link открывает бота и запускает /start premium
                        "url": "https://t.me/dota2ankets_bot?start=premium",
                    }]]
                },
            })


# ─────────────────────── API Routes ───────────────────────

ALLOWED_GAMES = {"all", "dota2", "cs2", "valorant", "mobile_legends", "pubg", "lol"}
ALLOWED_SEEK  = {"any", "male", "female"}


@app.get("/api/profiles")
async def get_profiles(user_id: int, game: str = "all",
                       seek: str = "any", limit: int = 20):
    # Валидация фильтров — только whitelist значений
    if game not in ALLOWED_GAMES:
        raise HTTPException(status_code=400, detail="Invalid game filter")
    if seek not in ALLOWED_SEEK:
        raise HTTPException(status_code=400, detail="Invalid seek filter")
    if limit < 1 or limit > 100:
        limit = 20

    pool = await get_pool()

    # Строим WHERE-условия без строковой интерполяции пользовательских данных.
    # game и seek уже проверены через whitelist — безопасно использовать в f-string.
    game_filter = "" if game == "all" else "AND ug.game = $6"
    seek_filter = "" if seek == "any" else "AND u.gender = $7"

    # Формируем параметры запроса
    params: list = [user_id, user_id, user_id, user_id, limit]
    if game != "all":
        params.append(game)
    if seek != "any":
        params.append(seek)

    query = f"""
        SELECT * FROM (
            SELECT DISTINCT ON (u.id)
                   u.id, u.name, u.age, u.gender, u.bio,
                   u.avatar_file_id, u.is_premium, u.username,
                   CASE WHEN l_in.from_user_id IS NOT NULL THEN 1 ELSE 0 END AS liked_me
            FROM users u
            JOIN user_games ug ON u.id = ug.user_id
            LEFT JOIN likes l_in
                   ON l_in.from_user_id = u.id AND l_in.to_user_id = $1
            WHERE u.id != $2
              AND u.is_active = TRUE
              AND u.id NOT IN (SELECT to_user_id FROM likes WHERE from_user_id = $3)
              AND u.id NOT IN (SELECT blocked_id FROM blocked_users WHERE blocker_id = $4)
              {game_filter} {seek_filter}
        ) sub
        ORDER BY liked_me DESC, is_premium DESC, RANDOM()
        LIMIT $5
    """

    rows = await pool.fetch(query, *params)
    users = [dict(r) for r in rows]

    # Подгружаем игры для каждого пользователя
    for u in users:
        game_rows = await pool.fetch(
            "SELECT game, rank, roles FROM user_games WHERE user_id = $1", u["id"]
        )
        u["games"] = [dict(g) for g in game_rows]

    return users


class LikeRequest(BaseModel):
    from_id: int
    to_id: int


@app.post("/api/like")
async def like_profile(req: LikeRequest):
    pool = await get_pool()

    async with pool.acquire() as conn:
        async with conn.transaction():
            # Пытаемся вставить лайк
            existing = await conn.fetchrow(
                "SELECT 1 FROM likes WHERE from_user_id = $1 AND to_user_id = $2",
                req.from_id, req.to_id,
            )
            if existing:
                return {"matched": False, "duplicate": True}

            await conn.execute(
                "INSERT INTO likes (from_user_id, to_user_id) VALUES ($1, $2)",
                req.from_id, req.to_id,
            )

            # Проверяем взаимный лайк
            mutual = await conn.fetchrow(
                "SELECT 1 FROM likes WHERE from_user_id = $1 AND to_user_id = $2",
                req.to_id, req.from_id,
            )
            matched = bool(mutual)

            if matched:
                min_id = min(req.from_id, req.to_id)
                max_id = max(req.from_id, req.to_id)
                await conn.execute(
                    "INSERT INTO matches (user1_id, user2_id) VALUES ($1, $2)"
                    " ON CONFLICT DO NOTHING",
                    min_id, max_id,
                )

            from_user = await fetch_user(pool, req.from_id)
            to_user   = await fetch_user(pool, req.to_id)

    # Уведомления вне транзакции
    if matched:
        await send_match_notifications(pool, from_user, to_user)
    else:
        if from_user and to_user:
            await send_liked_notification(
                pool, from_user, to_user["id"], bool(to_user.get("is_premium"))
            )

    return {"matched": matched}


@app.get("/api/check_user")
async def check_user(user_id: int):
    pool = await get_pool()
    row = await pool.fetchrow(
        "SELECT id, name FROM users WHERE id = $1", user_id
    )
    return {"registered": bool(row), "name": row["name"] if row else None}


@app.get("/api/matches")
async def get_matches(user_id: int):
    pool = await get_pool()
    rows = await pool.fetch("""
        SELECT u.id, u.name, u.age, u.gender, u.bio,
               u.avatar_file_id, u.is_premium, u.username
        FROM matches m
        JOIN users u ON (
            CASE WHEN m.user1_id = $1 THEN m.user2_id ELSE m.user1_id END = u.id
        )
        WHERE m.user1_id = $1 OR m.user2_id = $1
        ORDER BY m.created_at DESC
    """, user_id)

    matches = []
    for row in rows:
        u = dict(row)
        game_rows = await pool.fetch(
            "SELECT game, rank, roles FROM user_games WHERE user_id = $1", u["id"]
        )
        u["games"] = [dict(g) for g in game_rows]
        matches.append(u)

    return matches


# Статика — монтируется последней, чтобы не перекрывать API-маршруты
app.mount("/", StaticFiles(directory="webapp", html=True), name="webapp")
