import asyncpg
from datetime import datetime, timedelta
from typing import Optional

class Database:
    def __init__(self, url: str):
        self.url = url
        self.pool = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(self.url)

    async def get_user(self, user_id: int) -> Optional[dict]:
        async with self.pool.acquire() as conn:
            row = await conn.fetchrow("SELECT * FROM users WHERE id = $1", user_id)
            return dict(row) if row else None

    async def create_user(self, user_id, username, name, age, gender, seeking, bio=None, avatar_file_id=None):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO users (id, username, name, age, gender, seeking, bio, avatar_file_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (id) DO UPDATE SET
                    name=$3, age=$4, gender=$5, seeking=$6, bio=$7, avatar_file_id=$8, updated_at=NOW()
            """, user_id, username, name, age, gender, seeking, bio, avatar_file_id)

    async def add_user_game(self, user_id, game, rank=None, roles=None):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                INSERT INTO user_games (user_id, game, rank, roles)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (user_id, game) DO UPDATE SET rank=$3, roles=$4
            """, user_id, game, rank, roles or [])

    async def get_user_games(self, user_id: int) -> list:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("SELECT * FROM user_games WHERE user_id = $1", user_id)
            return [dict(r) for r in rows]

    async def get_profiles_for_user(self, user_id: int, limit: int = 20) -> list:
        async with self.pool.acquire() as conn:
            user = await self.get_user(user_id)
            user_games = await self.get_user_games(user_id)
            game_keys = [g["game"] for g in user_games]

            seeking = user["seeking"]
            gender_filter = "" if seeking == "any" else f"AND u.gender = '{seeking}'"

            rows = await conn.fetch(f"""
                SELECT DISTINCT u.*, array_agg(ug.game) as games
                FROM users u
                JOIN user_games ug ON u.id = ug.user_id
                WHERE u.id != $1
                AND u.is_active = TRUE
                AND ug.game = ANY($2::text[])
                AND u.id NOT IN (
                    SELECT to_user_id FROM likes WHERE from_user_id = $1
                )
                AND u.id NOT IN (
                    SELECT blocked_id FROM blocked_users WHERE blocker_id = $1
                )
                {gender_filter}
                GROUP BY u.id
                ORDER BY u.is_premium DESC, RANDOM()
                LIMIT $3
            """, user_id, game_keys, limit)
            return [dict(r) for r in rows]

    async def add_like(self, from_id: int, to_id: int) -> bool:
        async with self.pool.acquire() as conn:
            try:
                await conn.execute(
                    "INSERT INTO likes (from_user_id, to_user_id) VALUES ($1, $2)",
                    from_id, to_id
                )
            except asyncpg.UniqueViolationError:
                return False

            mutual = await conn.fetchval(
                "SELECT 1 FROM likes WHERE from_user_id=$1 AND to_user_id=$2",
                to_id, from_id
            )
            if mutual:
                min_id, max_id = min(from_id, to_id), max(from_id, to_id)
                await conn.execute("""
                    INSERT INTO matches (user1_id, user2_id) VALUES ($1, $2)
                    ON CONFLICT DO NOTHING
                """, min_id, max_id)
                return True
            return False

    async def increment_likes(self, user_id: int):
        async with self.pool.acquire() as conn:
            user = await self.get_user(user_id)
            now = datetime.now()
            if user["likes_reset_at"] and (now - user["likes_reset_at"]).days >= 1:
                await conn.execute(
                    "UPDATE users SET daily_likes=1, likes_reset_at=NOW() WHERE id=$1", user_id
                )
            else:
                await conn.execute(
                    "UPDATE users SET daily_likes=daily_likes+1 WHERE id=$1", user_id
                )

    async def get_matches(self, user_id: int) -> list:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT u.* FROM matches m
                JOIN users u ON (
                    CASE WHEN m.user1_id = $1 THEN m.user2_id ELSE m.user1_id END = u.id
                )
                WHERE m.user1_id = $1 OR m.user2_id = $1
                ORDER BY m.created_at DESC
            """, user_id)
            return [dict(r) for r in rows]

    async def get_who_liked_me(self, user_id: int) -> list:
        async with self.pool.acquire() as conn:
            rows = await conn.fetch("""
                SELECT u.* FROM likes l
                JOIN users u ON l.from_user_id = u.id
                WHERE l.to_user_id = $1
                AND l.from_user_id NOT IN (
                    SELECT to_user_id FROM likes WHERE from_user_id = $1
                )
                ORDER BY l.created_at DESC
            """, user_id)
            return [dict(r) for r in rows]

    async def activate_premium(self, user_id: int, days: int = 30):
        async with self.pool.acquire() as conn:
            await conn.execute("""
                UPDATE users SET is_premium=TRUE,
                premium_until=NOW() + INTERVAL '$1 days'
                WHERE id=$2
            """, days, user_id)

    async def toggle_active(self, user_id: int):
        async with self.pool.acquire() as conn:
            await conn.execute(
                "UPDATE users SET is_active = NOT is_active WHERE id=$1", user_id
            )
