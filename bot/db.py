import psycopg2
import psycopg2.extras
from datetime import datetime
from typing import Optional

class Database:
    def __init__(self, url: str):
        self.url = url
        self.conn = None

    async def connect(self):
        self.conn = psycopg2.connect(self.url)
        self.conn.autocommit = True

    def _cursor(self):
        if self.conn.closed:
            self.conn = psycopg2.connect(self.url)
            self.conn.autocommit = True
        return self.conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    async def get_user(self, user_id: int) -> Optional[dict]:
        cur = self._cursor()
        cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    async def create_user(self, user_id, username, name, age, gender, seeking, bio=None, avatar_file_id=None):
        cur = self._cursor()
        cur.execute("""
            INSERT INTO users (id, username, name, age, gender, seeking, bio, avatar_file_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                name=%s, age=%s, gender=%s, seeking=%s, bio=%s, avatar_file_id=%s, updated_at=NOW()
        """, (user_id, username, name, age, gender, seeking, bio, avatar_file_id,
              name, age, gender, seeking, bio, avatar_file_id))

    async def add_user_game(self, user_id, game, rank=None, roles=None):
        cur = self._cursor()
        cur.execute("""
            INSERT INTO user_games (user_id, game, rank, roles)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id, game) DO UPDATE SET rank=%s, roles=%s
        """, (user_id, game, rank, roles or [], rank, roles or []))

    async def get_user_games(self, user_id: int) -> list:
        cur = self._cursor()
        cur.execute("SELECT * FROM user_games WHERE user_id = %s", (user_id,))
        return [dict(r) for r in cur.fetchall()]

    async def get_profiles_for_user(self, user_id: int, limit: int = 20) -> list:
        user = await self.get_user(user_id)
        user_games = await self.get_user_games(user_id)
        game_keys = [g["game"] for g in user_games]
        if not game_keys:
            return []

        seeking = user["seeking"]
        gender_filter = "" if seeking == "any" else f"AND u.gender = '{seeking}'"

        cur = self._cursor()
        cur.execute(f"""
            SELECT DISTINCT u.*
            FROM users u
            JOIN user_games ug ON u.id = ug.user_id
            WHERE u.id != %s
            AND u.is_active = TRUE
            AND ug.game = ANY(%s)
            AND u.id NOT IN (
                SELECT to_user_id FROM likes WHERE from_user_id = %s
            )
            AND u.id NOT IN (
                SELECT blocked_id FROM blocked_users WHERE blocker_id = %s
            )
            {gender_filter}
            ORDER BY u.is_premium DESC
            LIMIT %s
        """, (user_id, game_keys, user_id, user_id, limit))
        return [dict(r) for r in cur.fetchall()]

    async def add_like(self, from_id: int, to_id: int) -> bool:
        cur = self._cursor()
        try:
            cur.execute(
                "INSERT INTO likes (from_user_id, to_user_id) VALUES (%s, %s)",
                (from_id, to_id)
            )
        except psycopg2.errors.UniqueViolation:
            self.conn.rollback()
            return False

        cur.execute(
            "SELECT 1 FROM likes WHERE from_user_id=%s AND to_user_id=%s",
            (to_id, from_id)
        )
        mutual = cur.fetchone()
        if mutual:
            min_id, max_id = min(from_id, to_id), max(from_id, to_id)
            cur.execute("""
                INSERT INTO matches (user1_id, user2_id) VALUES (%s, %s)
                ON CONFLICT DO NOTHING
            """, (min_id, max_id))
            return True
        return False

    async def increment_likes(self, user_id: int):
        cur = self._cursor()
        user = await self.get_user(user_id)
        now = datetime.now()
        if user["likes_reset_at"] and (now - user["likes_reset_at"]).days >= 1:
            cur.execute(
                "UPDATE users SET daily_likes=1, likes_reset_at=NOW() WHERE id=%s", (user_id,)
            )
        else:
            cur.execute(
                "UPDATE users SET daily_likes=daily_likes+1 WHERE id=%s", (user_id,)
            )

    async def get_matches(self, user_id: int) -> list:
        cur = self._cursor()
        cur.execute("""
            SELECT u.* FROM matches m
            JOIN users u ON (
                CASE WHEN m.user1_id = %s THEN m.user2_id ELSE m.user1_id END = u.id
            )
            WHERE m.user1_id = %s OR m.user2_id = %s
            ORDER BY m.created_at DESC
        """, (user_id, user_id, user_id))
        return [dict(r) for r in cur.fetchall()]

    async def get_who_liked_me(self, user_id: int) -> list:
        cur = self._cursor()
        cur.execute("""
            SELECT u.* FROM likes l
            JOIN users u ON l.from_user_id = u.id
            WHERE l.to_user_id = %s
            AND l.from_user_id NOT IN (
                SELECT to_user_id FROM likes WHERE from_user_id = %s
            )
            ORDER BY l.created_at DESC
        """, (user_id, user_id))
        return [dict(r) for r in cur.fetchall()]

    async def activate_premium(self, user_id: int, days: int = 30):
        cur = self._cursor()
        cur.execute("""
            UPDATE users SET is_premium=TRUE,
            premium_until=NOW() + INTERVAL '%s days'
            WHERE id=%s
        """, (days, user_id))

    async def update_user_field(self, user_id: int, field: str, value):
        allowed = {"name", "age", "bio", "avatar_file_id", "gender", "seeking"}
        if field not in allowed:
            return
        cur = self._cursor()
        cur.execute(f"UPDATE users SET {field}=%s, updated_at=NOW() WHERE id=%s", (value, user_id))

    async def delete_user_games(self, user_id: int):
        cur = self._cursor()
        cur.execute("DELETE FROM user_games WHERE user_id=%s", (user_id,))

    async def delete_user(self, user_id: int):
        cur = self._cursor()
        cur.execute("DELETE FROM users WHERE id=%s", (user_id,))

    async def toggle_active(self, user_id: int):
        cur = self._cursor()
        cur.execute(
            "UPDATE users SET is_active = NOT is_active WHERE id=%s", (user_id,)
        )
