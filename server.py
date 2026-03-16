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

class LikeRequest(BaseModel):
    from_id: int
    to_id: int

@app.get("/api/profiles")
def get_profiles(user_id: int, game: str = "all", seek: str = "any", limit: int = 20):
    conn = get_conn()
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    game_filter = "" if game == "all" else f"AND ug.game = '{game}'"
    seek_filter = "" if seek == "any" else f"AND u.gender = '{seek}'"
    cur.execute(f"""
        SELECT DISTINCT u.id, u.name, u.age, u.gender, u.bio,
               u.avatar_file_id, u.is_premium, u.username
        FROM users u
        JOIN user_games ug ON u.id = ug.user_id
        WHERE u.id != %s AND u.is_active = TRUE
        AND u.id NOT IN (SELECT to_user_id FROM likes WHERE from_user_id = %s)
        AND u.id NOT IN (SELECT blocked_id FROM blocked_users WHERE blocker_id = %s)
        {game_filter} {seek_filter}
        ORDER BY u.is_premium DESC LIMIT %s
    """, (user_id, user_id, user_id, limit))
    users = [dict(r) for r in cur.fetchall()]
    for u in users:
        cur.execute("SELECT game, rank, roles FROM user_games WHERE user_id = %s", (u["id"],))
        u["games"] = [dict(g) for g in cur.fetchall()]
    conn.close()
    return users

@app.post("/api/like")
def like_profile(req: LikeRequest):
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
    conn.close()
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
