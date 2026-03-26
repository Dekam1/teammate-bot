import asyncpg
from datetime import datetime, timedelta
from typing import Optional


class Database:
    def __init__(self, url: str):
        # asyncpg принимает DSN в формате postgresql://...
        # Если URL начинается с postgres://, asyncpg поддерживает оба варианта
        self.url = url
        self.pool: Optional[asyncpg.Pool] = None

    async def connect(self):
        self.pool = await asyncpg.create_pool(self.url, min_size=2, max_size=10)

    async def close(self):
        if self.pool:
            await self.pool.close()

    # ─────────────────────── Users ───────────────────────

    async def get_user(self, user_id: int) -> Optional[dict]:
        row = await self.pool.fetchrow(
            "SELECT * FROM users WHERE id = $1", user_id
        )
        return dict(row) if row else None

    async def create_user(self, user_id: int, username: Optional[str],
                          name: str, age: int, gender: str, seeking: str,
                          bio: Optional[str] = None,
                          avatar_file_id: Optional[str] = None):
        await self.pool.execute("""
            INSERT INTO users (id, username, name, age, gender, seeking, bio, avatar_file_id)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            ON CONFLICT (id) DO UPDATE SET
                username=$2, name=$3, age=$4, gender=$5,
                seeking=$6, bio=$7, avatar_file_id=$8, updated_at=NOW()
        """, user_id, username, name, age, gender, seeking, bio, avatar_file_id)

    async def update_user_field(self, user_id: int, field: str, value):
        allowed = {"name", "age", "bio", "avatar_file_id", "gender", "seeking", "username"}
        if field not in allowed:
            raise ValueError(f"Field '{field}' is not allowed to update")
        # field уже проверен через whitelist — интерполяция безопасна
        await self.pool.execute(
            f"UPDATE users SET {field}=$1, updated_at=NOW() WHERE id=$2",
            value, user_id
        )

    async def toggle_active(self, user_id: int):
        await self.pool.execute(
            "UPDATE users SET is_active = NOT is_active WHERE id=$1", user_id
        )

    async def delete_user(self, user_id: int):
        await self.pool.execute("DELETE FROM users WHERE id=$1", user_id)

    # ─────────────────────── Games ───────────────────────

    async def add_user_game(self, user_id: int, game: str,
                            rank: Optional[str] = None,
                            roles: Optional[list] = None):
        await self.pool.execute("""
            INSERT INTO user_games (user_id, game, rank, roles)
            VALUES ($1, $2, $3, $4)
            ON CONFLICT (user_id, game) DO UPDATE SET rank=$3, roles=$4
        """, user_id, game, rank, roles or [])

    async def get_user_games(self, user_id: int) -> list:
        rows = await self.pool.fetch(
            "SELECT * FROM user_games WHERE user_id = $1", user_id
        )
        return [dict(r) for r in rows]

    async def delete_user_games(self, user_id: int):
        await self.pool.execute(
            "DELETE FROM user_games WHERE user_id=$1", user_id
        )

    # ─────────────────────── Profiles feed ───────────────────────

    async def get_profiles_for_user(self, user_id: int, limit: int = 20) -> list:
        user = await self.get_user(user_id)
        if not user:
            return []
        user_games = await self.get_user_games(user_id)
        game_keys = [g["game"] for g in user_games]
        if not game_keys:
            return []

        seeking = user["seeking"]
        # Параметризованный запрос — нет SQL injection
        if seeking == "any":
            rows = await self.pool.fetch("""
                SELECT DISTINCT u.*
                FROM users u
                JOIN user_games ug ON u.id = ug.user_id
                WHERE u.id != $1
                  AND u.is_active = TRUE
                  AND ug.game = ANY($2)
                  AND u.id NOT IN (SELECT to_user_id FROM likes WHERE from_user_id = $1)
                  AND u.id NOT IN (SELECT blocked_id FROM blocked_users WHERE blocker_id = $1)
                ORDER BY u.is_premium DESC
                LIMIT $3
            """, user_id, game_keys, limit)
        else:
            rows = await self.pool.fetch("""
                SELECT DISTINCT u.*
                FROM users u
                JOIN user_games ug ON u.id = ug.user_id
                WHERE u.id != $1
                  AND u.is_active = TRUE
                  AND ug.game = ANY($2)
                  AND u.gender = $3
                  AND u.id NOT IN (SELECT to_user_id FROM likes WHERE from_user_id = $1)
                  AND u.id NOT IN (SELECT blocked_id FROM blocked_users WHERE blocker_id = $1)
                ORDER BY u.is_premium DESC
                LIMIT $4
            """, user_id, game_keys, seeking, limit)

        return [dict(r) for r in rows]

    # ─────────────────────── Likes ───────────────────────

    async def add_like(self, from_id: int, to_id: int) -> bool:
        """
        Добавляет лайк. Возвращает True, если образовался матч.
        Единственное место с логикой лайка — дублирования с server.py нет
        (server.py использует свой inline-код для транзакционности через asyncpg).
        """
        async with self.pool.acquire() as conn:
            async with conn.transaction():
                existing = await conn.fetchrow(
                    "SELECT 1 FROM likes WHERE from_user_id=$1 AND to_user_id=$2",
                    from_id, to_id,
                )
                if existing:
                    return False  # дубль

                await conn.execute(
                    "INSERT INTO likes (from_user_id, to_user_id) VALUES ($1, $2)",
                    from_id, to_id,
                )

                mutual = await conn.fetchrow(
                    "SELECT 1 FROM likes WHERE from_user_id=$1 AND to_user_id=$2",
                    to_id, from_id,
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
        """Увеличивает счётчик дневных лайков, сбрасывает его если прошли сутки."""
        user = await self.get_user(user_id)
        if not user:
            return
        now = datetime.now()
        reset_at = user.get("likes_reset_at")
        if reset_at and (now - reset_at).total_seconds() >= 86400:
            await self.pool.execute(
                "UPDATE users SET daily_likes=1, likes_reset_at=NOW() WHERE id=$1",
                user_id,
            )
        else:
            await self.pool.execute(
                "UPDATE users SET daily_likes=daily_likes+1 WHERE id=$1",
                user_id,
            )

    # ─────────────────────── Matches ───────────────────────

    async def get_matches(self, user_id: int) -> list:
        rows = await self.pool.fetch("""
            SELECT u.* FROM matches m
            JOIN users u ON (
                CASE WHEN m.user1_id = $1 THEN m.user2_id ELSE m.user1_id END = u.id
            )
            WHERE m.user1_id = $1 OR m.user2_id = $1
            ORDER BY m.created_at DESC
        """, user_id)
        return [dict(r) for r in rows]

    # ─────────────────────── Who liked me (Premium) ───────────────────────

    async def get_who_liked_me(self, user_id: int) -> list:
        rows = await self.pool.fetch("""
            SELECT u.* FROM likes l
            JOIN users u ON l.from_user_id = u.id
            WHERE l.to_user_id = $1
              AND l.from_user_id NOT IN (
                  SELECT to_user_id FROM likes WHERE from_user_id = $1
              )
            ORDER BY l.created_at DESC
        """, user_id)
        return [dict(r) for r in rows]

    # ─────────────────────── Premium ───────────────────────

    async def activate_premium(self, user_id: int, days: int = 30):
        await self.pool.execute("""
            UPDATE users
            SET is_premium=TRUE,
                premium_until=NOW() + ($1 * INTERVAL '1 day')
            WHERE id=$2
        """, days, user_id)

    # ─────────────────────── Block ───────────────────────

    async def block_user(self, blocker_id: int, blocked_id: int):
        await self.pool.execute("""
            INSERT INTO blocked_users (blocker_id, blocked_id)
            VALUES ($1, $2)
            ON CONFLICT DO NOTHING
        """, blocker_id, blocked_id)
