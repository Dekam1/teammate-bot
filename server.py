from fastapi import FastAPI, HTTPException, UploadFile, File, Form
from fastapi.staticfiles import StaticFiles
from fastapi.responses import Response
from pydantic import BaseModel
import psycopg2
import psycopg2.extras
import os
import httpx
from dotenv import load_dotenv

load_dotenv()
app = FastAPI()

DATABASE_URL = os.getenv("DATABASE_URL")
BOT_TOKEN = os.getenv("BOT_TOKEN")


def get_conn():
    return psycopg2.connect(DATABASE_URL)


def get_user(cur, user_id):
    cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
    row = cur.fetchone()
    return dict(row) if row else None


def get_write_url(user_id: int, username: str = None) -> str:
    """ИСПРАВЛЕНО: корректная ссылка даже если username отсутствует."""
    if username:
        return f"https://t.me/{username}"
    return f"tg://user?id={user_id}"


async def get_user_games_text(cur, user_id):
    cur.execute("SELECT game, rank, roles FROM user_games WHERE user_id = %s", (user_id,))
    rows = cur.fetchall()
    GAMES = {
        "dota2": "🎮 Dota 2", "cs2": "🔫 CS2", "valorant": "⚡ Valorant",
        "mobile_legends": "📱 Mobile Legends", "pubg": "🪖 PUBG", "lol": "⚔️ LoL"
    }
    parts = []
    for r in rows:
        name = GAMES.get(r['game'], r['game'])
        rank = f" · {r['rank']}" if r.get('rank') else ""
        roles = f" ({', '.join(r['roles'])})" if r.get('roles') else ""
        parts.append(f"{name}{rank}{roles}")
    return "\n".join(parts) if parts else "Не указаны"


async def notify_user(client, sender_id, receiver):
    # ИСПРАВЛЕНО: try/finally — соединение всегда закрывается
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        games_text = await get_user_games_text(cur, receiver['id'])
    finally:
        conn.close()

    gender_labels = {"male": "Парень", "female": "Девушка", "any": "–"}
    gender = gender_labels.get(receiver.get('gender', ''), '–')

    text = (
        f"🎉 *Это матч!*\n\n"
        f"👤 *{receiver['name']}*, {receiver['age']} лет · {gender}\n"
        f"📝 {receiver.get('bio') or 'Нет описания'}\n\n"
        f"🎮 *Игры:*\n{games_text}"
    )

    # ИСПРАВЛЕНО: используем get_write_url для корректной ссылки без username
    write_url = get_write_url(receiver['id'], receiver.get('username'))

    reply_markup = {
        "inline_keyboard": [[{
            "text": f"✍️ Написать {receiver['name']}",
            "url": write_url
        }]]
    }
    try:
        if receiver.get('avatar_file_id'):
            payload = {
                "chat_id": sender_id,
                "photo": receiver['avatar_file_id'],
                "caption": text,
                "parse_mode": "Markdown",
                "reply_markup": reply_markup
            }
            await client.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto", json=payload)
        else:
            payload = {
                "chat_id": sender_id,
                "text": text,
                "parse_mode": "Markdown",
                "reply_markup": reply_markup
            }
            await client.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json=payload)
    except Exception as e:
        print(f"Notify error for {sender_id}: {e}")


async def send_match_notifications(user1, user2):
    if not BOT_TOKEN:
        return
    async with httpx.AsyncClient() as client:
        await notify_user(client, user1['id'], user2)
        await notify_user(client, user2['id'], user1)


async def send_liked_notification(liker, target_id, is_premium):
    if not BOT_TOKEN:
        return
    async with httpx.AsyncClient() as client:
        if is_premium:
            text = (
                f"❤️ *Тебя лайкнул {liker['name']}!*\n\n"
                f"👤 {liker['name']}, {liker['age']} лет\n"
                f"📝 {liker.get('bio') or 'Нет описания'}\n\n"
                f"Открой свайп и лайкни в ответ!"
            )
            # ИСПРАВЛЕНО: используем get_write_url
            write_url = get_write_url(liker['id'], liker.get('username'))
            reply_markup = {"inline_keyboard": [[{
                "text": f"✍️ Написать {liker['name']}",
                "url": write_url
            }]]}
            if liker.get('avatar_file_id'):
                await client.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto",
                    json={
                        "chat_id": target_id,
                        "photo": liker['avatar_file_id'],
                        "caption": text,
                        "parse_mode": "Markdown",
                        "reply_markup": reply_markup
                    }
                )
            else:
                await client.post(
                    f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
                    json={
                        "chat_id": target_id,
                        "text": text,
                        "parse_mode": "Markdown",
                        "reply_markup": reply_markup
                    }
                )
        else:
            text = "❤️ Кто-то лайкнул твою анкету!\n\nОткрой свайп и найди своего тиммейта 🎮"
            payload = {
                "chat_id": target_id,
                "text": text,
                "reply_markup": {
                    "inline_keyboard": [[{
                        "text": "💎 Узнать кто (Premium)",
                        "callback_data": "buy_premium"
                    }]]
                }
            }
            await client.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json=payload)


class LikeRequest(BaseModel):
    from_id: int
    to_id: int


@app.get("/api/profiles")
def get_profiles(user_id: int, game: str = "all", seek: str = "any", limit: int = 20):
    # ИСПРАВЛЕНО: убрана SQL-инъекция через f-string, используем параметризованные запросы
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

        ALLOWED_GAMES = {"all", "dota2", "cs2", "valorant", "mobile_legends", "pubg", "lol"}
        ALLOWED_SEEK = {"any", "male", "female"}

        if game not in ALLOWED_GAMES:
            game = "all"
        if seek not in ALLOWED_SEEK:
            seek = "any"

        if game == "all" and seek == "any":
            cur.execute("""
                SELECT * FROM (
                    SELECT DISTINCT ON (u.id) u.id, u.name, u.age, u.gender, u.bio,
                           u.avatar_file_id, u.is_premium, u.username,
                           CASE WHEN l_in.from_user_id IS NOT NULL THEN 1 ELSE 0 END as liked_me
                    FROM users u
                    JOIN user_games ug ON u.id = ug.user_id
                    LEFT JOIN likes l_in ON l_in.from_user_id = u.id AND l_in.to_user_id = %s
                    WHERE u.id != %s AND u.is_active = TRUE
                    AND u.id NOT IN (SELECT to_user_id FROM likes WHERE from_user_id = %s)
                    AND u.id NOT IN (SELECT blocked_id FROM blocked_users WHERE blocker_id = %s)
                ) sub
                ORDER BY liked_me DESC, is_premium DESC, RANDOM()
                LIMIT %s
            """, (user_id, user_id, user_id, user_id, limit))

        elif game == "all" and seek != "any":
            cur.execute("""
                SELECT * FROM (
                    SELECT DISTINCT ON (u.id) u.id, u.name, u.age, u.gender, u.bio,
                           u.avatar_file_id, u.is_premium, u.username,
                           CASE WHEN l_in.from_user_id IS NOT NULL THEN 1 ELSE 0 END as liked_me
                    FROM users u
                    JOIN user_games ug ON u.id = ug.user_id
                    LEFT JOIN likes l_in ON l_in.from_user_id = u.id AND l_in.to_user_id = %s
                    WHERE u.id != %s AND u.is_active = TRUE AND u.gender = %s
                    AND u.id NOT IN (SELECT to_user_id FROM likes WHERE from_user_id = %s)
                    AND u.id NOT IN (SELECT blocked_id FROM blocked_users WHERE blocker_id = %s)
                ) sub
                ORDER BY liked_me DESC, is_premium DESC, RANDOM()
                LIMIT %s
            """, (user_id, user_id, seek, user_id, user_id, limit))

        elif game != "all" and seek == "any":
            cur.execute("""
                SELECT * FROM (
                    SELECT DISTINCT ON (u.id) u.id, u.name, u.age, u.gender, u.bio,
                           u.avatar_file_id, u.is_premium, u.username,
                           CASE WHEN l_in.from_user_id IS NOT NULL THEN 1 ELSE 0 END as liked_me
                    FROM users u
                    JOIN user_games ug ON u.id = ug.user_id
                    LEFT JOIN likes l_in ON l_in.from_user_id = u.id AND l_in.to_user_id = %s
                    WHERE u.id != %s AND u.is_active = TRUE AND ug.game = %s
                    AND u.id NOT IN (SELECT to_user_id FROM likes WHERE from_user_id = %s)
                    AND u.id NOT IN (SELECT blocked_id FROM blocked_users WHERE blocker_id = %s)
                ) sub
                ORDER BY liked_me DESC, is_premium DESC, RANDOM()
                LIMIT %s
            """, (user_id, user_id, game, user_id, user_id, limit))

        else:
            cur.execute("""
                SELECT * FROM (
                    SELECT DISTINCT ON (u.id) u.id, u.name, u.age, u.gender, u.bio,
                           u.avatar_file_id, u.is_premium, u.username,
                           CASE WHEN l_in.from_user_id IS NOT NULL THEN 1 ELSE 0 END as liked_me
                    FROM users u
                    JOIN user_games ug ON u.id = ug.user_id
                    LEFT JOIN likes l_in ON l_in.from_user_id = u.id AND l_in.to_user_id = %s
                    WHERE u.id != %s AND u.is_active = TRUE AND ug.game = %s AND u.gender = %s
                    AND u.id NOT IN (SELECT to_user_id FROM likes WHERE from_user_id = %s)
                    AND u.id NOT IN (SELECT blocked_id FROM blocked_users WHERE blocker_id = %s)
                ) sub
                ORDER BY liked_me DESC, is_premium DESC, RANDOM()
                LIMIT %s
            """, (user_id, user_id, game, seek, user_id, user_id, limit))

        users = [dict(r) for r in cur.fetchall()]
        for u in users:
            cur.execute("SELECT game, rank, roles FROM user_games WHERE user_id = %s", (u["id"],))
            u["games"] = [dict(g) for g in cur.fetchall()]
        return users
    finally:
        # ИСПРАВЛЕНО: соединение всегда закрывается
        conn.close()


@app.post("/api/like")
async def like_profile(req: LikeRequest):
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        try:
            cur.execute("INSERT INTO likes (from_user_id, to_user_id) VALUES (%s, %s)",
                        (req.from_id, req.to_id))
            conn.commit()
        except psycopg2.errors.UniqueViolation:
            conn.rollback()
            return {"matched": False, "duplicate": True}

        cur.execute("SELECT 1 FROM likes WHERE from_user_id=%s AND to_user_id=%s",
                    (req.to_id, req.from_id))
        matched = bool(cur.fetchone())

        if matched:
            min_id, max_id = min(req.from_id, req.to_id), max(req.from_id, req.to_id)
            cur.execute(
                "INSERT INTO matches (user1_id, user2_id) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                (min_id, max_id)
            )
            conn.commit()
            from_user = get_user(cur, req.from_id)
            to_user = get_user(cur, req.to_id)
            conn.close()
            await send_match_notifications(from_user, to_user)
        else:
            liker = get_user(cur, req.from_id)
            target = get_user(cur, req.to_id)
            conn.close()
            if liker and target:
                await send_liked_notification(liker, target['id'], target['is_premium'])

        return {"matched": matched}
    except Exception as e:
        conn.close()
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/check_user")
def check_user(user_id: int):
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT id, name FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        return {"registered": bool(row), "name": row["name"] if row else None}
    finally:
        conn.close()


@app.get("/api/matches")
def get_matches(user_id: int):
    # ИСПРАВЛЕНО: функция была обрезана — теперь полная реализация
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("""
            SELECT u.* FROM matches m
            JOIN users u ON (
                CASE WHEN m.user1_id = %s THEN m.user2_id ELSE m.user1_id END = u.id
            )
            WHERE m.user1_id = %s OR m.user2_id = %s
            ORDER BY m.created_at DESC
        """, (user_id, user_id, user_id))
        matches = [dict(r) for r in cur.fetchall()]

        for m in matches:
            cur.execute("SELECT game, rank, roles FROM user_games WHERE user_id = %s", (m["id"],))
            m["games"] = [dict(g) for g in cur.fetchall()]
            # ИСПРАВЛЕНО: добавляем write_url с поддержкой отсутствия username
            m["write_url"] = get_write_url(m["id"], m.get("username"))

        return matches
    finally:
        conn.close()


@app.get("/api/user")
def get_user_info(user_id: int):
    conn = get_conn()
    try:
        cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
        cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        if not row:
            raise HTTPException(status_code=404, detail="User not found")
        user = dict(row)
        cur.execute("SELECT game, rank, roles FROM user_games WHERE user_id = %s", (user_id,))
        user["games"] = [dict(g) for g in cur.fetchall()]
        return user
    finally:
        conn.close()


app.mount("/", StaticFiles(directory="webapp", html=True), name="webapp")
