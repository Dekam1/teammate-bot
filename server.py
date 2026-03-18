from fastapi import FastAPI, HTTPException
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

async def notify_user(client, sender_id, receiver):
    username = f"@{receiver['username']}" if receiver.get('username') else "нет username"
    text = (
        f"🎉 *Это матч!*\n\n"
        f"👤 *{receiver['name']}*, {receiver['age']} лет\n"
        f"📝 {receiver.get('bio') or 'Нет описания'}\n\n"
        f"Контакт: {username}"
    )
    reply_markup = None
    if receiver.get('username'):
        reply_markup = {
            "inline_keyboard": [[{
                "text": f"✍️ Написать {receiver['name']}",
                "url": f"https://t.me/{receiver['username']}"
            }]]
        }
    try:
        if receiver.get('avatar_file_id'):
            payload = {"chat_id": sender_id, "photo": receiver['avatar_file_id'], "caption": text, "parse_mode": "Markdown"}
            if reply_markup:
                payload["reply_markup"] = reply_markup
            await client.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto", json=payload)
        else:
            payload = {"chat_id": sender_id, "text": text, "parse_mode": "Markdown"}
            if reply_markup:
                payload["reply_markup"] = reply_markup
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
    """Уведомить пользователя что его лайкнули"""
    if not BOT_TOKEN:
        return
    async with httpx.AsyncClient() as client:
        if is_premium:
            # Премиум — показываем кто лайкнул
            text = (
                f"❤️ *Тебя лайкнул {liker['name']}!*\n\n"
                f"👤 {liker['name']}, {liker['age']} лет\n"
                f"📝 {liker.get('bio') or 'Нет описания'}\n\n"
                f"Открой свайп и лайкни в ответ!"
            )
            payload = {"chat_id": target_id, "text": text, "parse_mode": "Markdown"}
            if liker.get('avatar_file_id'):
                payload_photo = {"chat_id": target_id, "photo": liker['avatar_file_id'], "caption": text, "parse_mode": "Markdown"}
                await client.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendPhoto", json=payload_photo)
            else:
                await client.post(f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage", json=payload)
        else:
            # Бесплатно — только что лайкнули, без имени
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
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    game_filter = "" if game == "all" else f"AND ug.game = '{game}'"
    seek_filter = "" if seek == "any" else f"AND u.gender = '{seek}'"

    # Сначала те кто лайкнул текущего пользователя (приоритет)
    cur.execute(f"""
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
            {game_filter} {seek_filter}
        ) sub
        ORDER BY liked_me DESC, is_premium DESC, RANDOM()
        LIMIT %s
    """, (user_id, user_id, user_id, user_id, limit))
    users = [dict(r) for r in cur.fetchall()]
    for u in users:
        cur.execute("SELECT game, rank, roles FROM user_games WHERE user_id = %s", (u["id"],))
        u["games"] = [dict(g) for g in cur.fetchall()]
    conn.close()
    return users

@app.post("/api/like")
async def like_profile(req: LikeRequest):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    try:
        cur.execute("INSERT INTO likes (from_user_id, to_user_id) VALUES (%s, %s)", (req.from_id, req.to_id))
        conn.commit()
    except psycopg2.errors.UniqueViolation:
        conn.rollback()
        conn.close()
        return {"matched": False, "duplicate": True}

    cur.execute("SELECT 1 FROM likes WHERE from_user_id=%s AND to_user_id=%s", (req.to_id, req.from_id))
    matched = bool(cur.fetchone())

    if matched:
        min_id, max_id = min(req.from_id, req.to_id), max(req.from_id, req.to_id)
        cur.execute("INSERT INTO matches (user1_id, user2_id) VALUES (%s, %s) ON CONFLICT DO NOTHING", (min_id, max_id))
        conn.commit()
        from_user = get_user(cur, req.from_id)
        to_user = get_user(cur, req.to_id)
        conn.close()
        await send_match_notifications(from_user, to_user)
    else:
        # Не матч — уведомить что лайкнули
        liker = get_user(cur, req.from_id)
        target = get_user(cur, req.to_id)
        conn.close()
        if liker and target:
            await send_liked_notification(liker, target['id'], target['is_premium'])

    return {"matched": matched}

@app.get("/api/matches")
def get_matches(user_id: int):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT u.id, u.name, u.age, u.username, u.avatar_file_id
        FROM matches m
        JOIN users u ON (CASE WHEN m.user1_id=%s THEN m.user2_id ELSE m.user1_id END = u.id)
        WHERE m.user1_id=%s OR m.user2_id=%s
        ORDER BY m.created_at DESC
    """, (user_id, user_id, user_id))
    matches = [dict(r) for r in cur.fetchall()]
    for m in matches:
        cur.execute("SELECT game FROM user_games WHERE user_id=%s", (m["id"],))
        m["games"] = [r["game"] for r in cur.fetchall()]
    conn.close()
    return matches

@app.get("/api/who_liked_me")
def who_liked_me(user_id: int):
    """Для премиум — список кто лайкнул"""
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT u.id, u.name, u.age, u.username, u.avatar_file_id, u.bio
        FROM likes l
        JOIN users u ON l.from_user_id = u.id
        WHERE l.to_user_id = %s
        AND l.from_user_id NOT IN (SELECT to_user_id FROM likes WHERE from_user_id = %s)
        ORDER BY l.created_at DESC
    """, (user_id, user_id))
    result = [dict(r) for r in cur.fetchall()]
    conn.close()
    return result

@app.get("/api/photo/{file_id}")
async def get_photo(file_id: str):
    async with httpx.AsyncClient() as client:
        r = await client.get(f"https://api.telegram.org/bot{BOT_TOKEN}/getFile?file_id={file_id}")
        data = r.json()
        if not data.get("ok"):
            raise HTTPException(404)
        path = data["result"]["file_path"]
        img = await client.get(f"https://api.telegram.org/file/bot{BOT_TOKEN}/{path}")
        return Response(content=img.content, media_type="image/jpeg")

app.mount("/", StaticFiles(directory="webapp", html=True), name="webapp")
