# database.py
import os
import asyncpg
from contextlib import asynccontextmanager

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

# ---------------- CONNECTION POOL ----------------
pool: asyncpg.pool.Pool = None

async def init_pool():
    global pool
    if pool is None:
        pool = await asyncpg.create_pool(
            DATABASE_URL,
            min_size=1,
            max_size=10,  # Supabase free tier limit
            command_timeout=60
        )

@asynccontextmanager
async def get_conn():
    """
    Async context manager for a pooled connection.
    Usage:
        async with get_conn() as conn:
            await conn.execute("...")
    """
    async with pool.acquire() as conn:
        yield conn

# ---------------- INIT TABLE ----------------
async def init_db():
    async with get_conn() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS tracked_anime (
                user_id BIGINT,
                anime_id INTEGER,
                anime_name TEXT,
                alias TEXT,
                last_watched INTEGER DEFAULT 0,
                last_notified INTEGER DEFAULT 0,
                status TEXT DEFAULT 'watching',
                PRIMARY KEY (user_id, anime_id)
            )
        """)

# ---------------- ADD ----------------
async def add_anime(user_id, anime_id, anime_name, alias, episode=0, status="watching"):
    async with get_conn() as conn:
        await conn.execute("""
            INSERT INTO tracked_anime
            (user_id, anime_id, anime_name, alias, last_watched, last_notified, status)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            ON CONFLICT (user_id, anime_id) DO NOTHING
        """, user_id, anime_id, anime_name, alias, episode, episode, status)

# ---------------- UPDATE ----------------
async def update_progress(user_id, anime_id, episode):
    async with get_conn() as conn:
        await conn.execute("""
            UPDATE tracked_anime
            SET last_watched = $1, status = 'watching'
            WHERE user_id = $2 AND anime_id = $3
        """, episode, user_id, anime_id)

async def update_status(user_id, anime_id, status):
    async with get_conn() as conn:
        await conn.execute("""
            UPDATE tracked_anime
            SET status = $1
            WHERE user_id = $2 AND anime_id = $3
        """, status, user_id, anime_id)

async def update_last_notified(user_id, anime_id, episode):
    async with get_conn() as conn:
        await conn.execute("""
            UPDATE tracked_anime
            SET last_notified = $1
            WHERE user_id = $2 AND anime_id = $3
        """, episode, user_id, anime_id)

async def update_alias(user_id, anime_id, new_alias):
    async with get_conn() as conn:
        await conn.execute("""
            UPDATE tracked_anime
            SET alias = $1
            WHERE user_id = $2 AND anime_id = $3
        """, new_alias, user_id, anime_id)

# ---------------- GET ----------------
async def get_progress(user_id, identifier):
    async with get_conn() as conn:
        row = await conn.fetchrow("""
            SELECT anime_name, alias, last_watched, anime_id, status
            FROM tracked_anime
            WHERE user_id = $1
              AND (alias = $2 OR anime_name = $2)
        """, user_id, identifier)
        return row

async def list_tracked(user_id):
    async with get_conn() as conn:
        rows = await conn.fetch("""
            SELECT anime_name, alias, last_watched, status
            FROM tracked_anime
            WHERE user_id = $1
            ORDER BY anime_name
        """, user_id)
        return rows

async def get_aliases(user_id):
    async with get_conn() as conn:
        rows = await conn.fetch("""
            SELECT alias FROM tracked_anime WHERE user_id = $1
        """, user_id)
        return [r['alias'] for r in rows]

async def get_all_tracked():
    async with get_conn() as conn:
        rows = await conn.fetch("""
            SELECT user_id, anime_id, last_watched, last_notified
            FROM tracked_anime
        """)
        return rows

# ---------------- DELETE ----------------
async def remove_anime(user_id, anime_id):
    async with get_conn() as conn:
        await conn.execute("""
            DELETE FROM tracked_anime
            WHERE user_id = $1 AND anime_id = $2
        """, user_id, anime_id)
