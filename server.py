from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
import asyncpg
import os
import httpx
from dotenv import load_dotenv

load_dotenv()
app = FastAPI()

DATABASE_URL = os.getenv("DATABASE_URL")
BOT_TOKEN = os.getenv("BOT_TOKEN")
pool = None

@app.on_event("startup")
async def startup():
    global pool
    pool = await asyncpg.create_pool(DATABASE_URL)

class LikeRequest(BaseModel):
    from_id: int
    to_id: int

@app.get("/api/profiles")
async def get_profiles(user_id: int, game: str = "all", seek: str = "any", limit: int = 20):
    async with pool.acquire() as conn:
        game_filter = "" if game == "all" else f"AND ug.game = '{game}'"
        seek_filter = "" if seek == "any" else f"AND u.gender = '{seek}'"

        rows = await conn.fetch(f"""
            SELECT DISTINCT u.id, u.name, u.age, u.gender, u.bio,
                   u.avatar_file_id, u.is_premium, u.username,
                   array_agg(DISTINCT ug.game) as games
            FROM users u
            JOIN user_games ug ON u.id = ug.user_id
            WHERE u.id != $1
            AND u.is_active = TRUE
            AND u.id NOT IN (SELECT to_user_id FROM likes WHERE from_user_id = $1)
            AND u.id NOT IN (SELECT blocked_id FROM blocked_users WHERE blocker_id = $1)
            {game_filter}
            {seek_filter}
            GROUP BY u.id
            ORDER BY u.is_premium DESC, RANDOM()
            LIMIT $2
        """, user_id, limit)

        result = []
        for r in rows:
            p = dict(r)
            game_rows = await conn.fetch(
                "SELECT game, rank, roles FROM user_games WHERE user_id = $1", p["id"]
            )
            p["games"] = [dict(g) for g in game_rows]
            result.append(p)
        return result

@app.post("/api/like")
async def like_profile(req: LikeRequest):
    async with pool.acquire() as conn:
        try:
            await conn.execute(
                "INSERT INTO likes (from_user_id, to_user_id) VALUES ($1, $2)",
                req.from_id, req.to_id
            )
        except asyncpg.UniqueViolationError:
            return {"matched": False, "duplicate": True}

        mutual = await conn.fetchval(
            "SELECT 1 FROM likes WHERE from_user_id=$1 AND to_user_id=$2",
            req.to_id, req.from_id
        )
        matched = bool(mutual)
        if matched:
            min_id, max_id = min(req.from_id, req.to_id), max(req.from_id, req.to_id)
            await conn.execute(
                "INSERT INTO matches (user1_id, user2_id) VALUES ($1, $2) ON CONFLICT DO NOTHING",
                min_id, max_id
            )
        return {"matched": matched}

@app.get("/api/matches")
async def get_matches(user_id: int):
    async with pool.acquire() as conn:
        rows = await conn.fetch("""
            SELECT u.id, u.name, u.age, u.username, u.avatar_file_id,
                   array_agg(ug.game) as games
            FROM matches m
            JOIN users u ON (
                CASE WHEN m.user1_id = $1 THEN m.user2_id ELSE m.user1_id END = u.id
            )
            LEFT JOIN user_games ug ON u.id = ug.user_id
            WHERE m.user1_id = $1 OR m.user2_id = $1
            GROUP BY u.id
            ORDER BY m.created_at DESC
        """, user_id)
        return [dict(r) for r in rows]

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
