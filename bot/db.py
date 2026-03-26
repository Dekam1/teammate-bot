import psycopg2
import psycopg2.extras
from datetime import datetime
from typing import Optional
import asyncio
from functools import partial


class Database:
    def __init__(self, url: str):
        self.url = url
        self.conn = None

    async def connect(self):
        loop = asyncio.get_event_loop()
        self.conn = await loop.run_in_executor(None, lambda: psycopg2.connect(self.url))
        self.conn.autocommit = True

    def _get_conn(self):
        """Проверяем соединение и переподключаемся если нужно."""
        if self.conn is None or self.conn.closed:
            self.conn = psycopg2.connect(self.url)
            self.conn.autocommit = True
        return self.conn

    def _cursor(self):
        return self._get_conn().cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    async def _run(self, func, *args, **kwargs):
        """Запускает синхронную функцию в executor, чтобы не блокировать event loop."""
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, partial(func, *args, **kwargs))

    def _get_user_sync(self, user_id: int):
        cur = self._cursor()
        cur.execute("SELECT * FROM users WHERE id = %s", (user_id,))
        row = cur.fetchone()
        return dict(row) if row else None

    async def get_user(self, user_id: int) -> Optional[dict]:
        return await self._run(self._get_user_sync, user_id)

    def _create_user_sync(self, user_id, username, name, age, gender, seeking, bio, avatar_file_id):
        cur = self._cursor()
        cur.execute("""
            INSERT INTO users (id, username, name, age, gender, seeking, bio, avatar_file_id)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (id) DO UPDATE SET
                name=%s, age=%s, gender=%s, seeking=%s, bio=%s, avatar_file_id=%s, updated_at=NOW()
        """, (user_id, username, name, age, gender, seeking, bio, avatar_file_id,
              name, age, gender, seeking, bio, avatar_file_id))

    async def create_user(self, user_id, username, name, age, gender, seeking, bio=None, avatar_file_id=None):
        await self._run(self._create_user_sync, user_id, username, name, age, gender, seeking, bio, avatar_file_id)

    def _add_user_game_sync(self, user_id, game, rank, roles):
        cur = self._cursor()
        cur.execute("""
            INSERT INTO user_games (user_id, game, rank, roles)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (user_id, game) DO UPDATE SET rank=%s, roles=%s
        """, (user_id, game, rank, roles or [], rank, roles or []))

    async def add_user_game(self, user_id, game, rank=None, roles=None):
        await self._run(self._add_user_game_sync, user_id, game, rank, roles)

    def _get_user_games_sync(self, user_id: int):
        cur = self._cursor()
        cur.execute("SELECT * FROM user_games WHERE user_id = %s", (user_id,))
        return [dict(r) for r in cur.fetchall()]

    async def get_user_games(self, user_id: int) -> list:
        return await self._run(self._get_user_games_sync, user_id)

    def _get_profiles_sync(self, user_id: int, limit: int = 20):
        user = self._get_user_sync(user_id)
        if not user:
            return []
        user_games_cur = self._cursor()
        user_games_cur.execute("SELECT game FROM user_games WHERE user_id = %s", (user_id,))
        game_keys = [r['game'] for r in user_games_cur.fetchall()]
        if not game_keys:
            return []

        seeking = user["seeking"]
        cur = self._cursor()

        # ИСПРАВЛЕНО: убрана SQL-инъекция через f-string, используем параметры
        if seeking == "any":
            cur.execute("""
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
                ORDER BY u.is_premium DESC
                LIMIT %s
            """, (user_id, game_keys, user_id, user_id, limit))
        else:
            cur.execute("""
                SELECT DISTINCT u.*
                FROM users u
                JOIN user_games ug ON u.id = ug.user_id
                WHERE u.id != %s
                AND u.is_active = TRUE
                AND ug.game = ANY(%s)
                AND u.gender = %s
                AND u.id NOT IN (
                    SELECT to_user_id FROM likes WHERE from_user_id = %s
                )
                AND u.id NOT IN (
                    SELECT blocked_id FROM blocked_users WHERE blocker_id = %s
                )
                ORDER BY u.is_premium DESC
                LIMIT %s
            """, (user_id, game_keys, seeking, user_id, user_id, limit))

        return [dict(r) for r in cur.fetchall()]

    async def get_profiles_for_user(self, user_id: int, limit: int = 20) -> list:
        return await self._run(self._get_profiles_sync, user_id, limit)

    def _add_like_sync(self, from_id: int, to_id: int) -> bool:
        cur = self._cursor()
        try:
            cur.execute(
                "INSERT INTO likes (from_user_id, to_user_id) VALUES (%s, %s)",
                (from_id, to_id)
            )
        except psycopg2.errors.UniqueViolation:
            # ИСПРАВЛЕНО: убран rollback при autocommit=True — он не нужен и вызывал ошибку
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

    async def add_like(self, from_id: int, to_id: int) -> bool:
        return await self._run(self._add_like_sync, from_id, to_id)

    def _check_and_reset_likes_sync(self, user_id: int):
        """ИСПРАВЛЕНО: проверяет и сбрасывает лимит лайков если прошли сутки."""
        user = self._get_user_sync(user_id)
        if not user:
            return
        now = datetime.now()
        reset_at = user.get("likes_reset_at")
        # Проверяем None и что прошли сутки
        if reset_at is None or (now - reset_at).total_seconds() >= 86400:
            cur = self._cursor()
            cur.execute(
                "UPDATE users SET daily_likes=0, likes_reset_at=NOW() WHERE id=%s",
                (user_id,)
            )

    async def check_and_reset_likes(self, user_id: int):
        await self._run(self._check_and_reset_likes_sync, user_id)

    def _increment_likes_sync(self, user_id: int):
        cur = self._cursor()
        cur.execute(
            "UPDATE users SET daily_likes=daily_likes+1 WHERE id=%s", (user_id,)
        )

    async def increment_likes(self, user_id: int):
        await self._run(self._increment_likes_sync, user_id)

    def _get_matches_sync(self, user_id: int) -> list:
        cur = self._cursor()
        # ИСПРАВЛЕНО: восстановлен полный запрос (был обрезан)
        cur.execute("""
            SELECT u.* FROM matches m
            JOIN users u ON (
                CASE WHEN m.user1_id = %s THEN m.user2_id ELSE m.user1_id END = u.id
            )
            WHERE m.user1_id = %s OR m.user2_id = %s
            ORDER BY m.created_at DESC
        """, (user_id, user_id, user_id))
        return [dict(r) for r in cur.fetchall()]

    async def get_matches(self, user_id: int) -> list:
        return await self._run(self._get_matches_sync, user_id)

    def _get_who_liked_me_sync(self, user_id: int) -> list:
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

    async def get_who_liked_me(self, user_id: int) -> list:
        return await self._run(self._get_who_liked_me_sync, user_id)

    def _activate_premium_sync(self, user_id: int, days: int = 30):
        cur = self._cursor()
        # ИСПРАВЛЕНО: SQL-инъекция в INTERVAL — теперь используем умножение
        cur.execute("""
            UPDATE users SET is_premium=TRUE,
            premium_until=NOW() + (INTERVAL '1 day' * %s)
            WHERE id=%s
        """, (days, user_id))

    async def activate_premium(self, user_id: int, days: int = 30):
        await self._run(self._activate_premium_sync, user_id, days)

    def _update_user_field_sync(self, user_id: int, field: str, value):
        allowed = {"name", "age", "bio", "avatar_file_id", "gender", "seeking"}
        if field not in allowed:
            return
        cur = self._cursor()
        cur.execute(f"UPDATE users SET {field}=%s, updated_at=NOW() WHERE id=%s", (value, user_id))

    async def update_user_field(self, user_id: int, field: str, value):
        await self._run(self._update_user_field_sync, user_id, field, value)

    def _delete_user_games_sync(self, user_id: int):
        cur = self._cursor()
        cur.execute("DELETE FROM user_games WHERE user_id=%s", (user_id,))

    async def delete_user_games(self, user_id: int):
        await self._run(self._delete_user_games_sync, user_id)

    def _delete_user_sync(self, user_id: int):
        cur = self._cursor()
        cur.execute("DELETE FROM users WHERE id=%s", (user_id,))

    async def delete_user(self, user_id: int):
        await self._run(self._delete_user_sync, user_id)

    def _toggle_active_sync(self, user_id: int):
        cur = self._cursor()
        cur.execute(
            "UPDATE users SET is_active = NOT is_active WHERE id=%s", (user_id,)
        )

    async def toggle_active(self, user_id: int):
        await self._run(self._toggle_active_sync, user_id)

    def _block_user_sync(self, blocker_id: int, blocked_id: int):
        """ИСПРАВЛЕНО: добавлен метод для блокировки (репорт)."""
        cur = self._cursor()
        cur.execute("""
            INSERT INTO blocked_users (blocker_id, blocked_id)
            VALUES (%s, %s)
            ON CONFLICT DO NOTHING
        """, (blocker_id, blocked_id))

    async def block_user(self, blocker_id: int, blocked_id: int):
        await self._run(self._block_user_sync, blocker_id, blocked_id)
