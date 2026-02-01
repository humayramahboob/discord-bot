import os
import psycopg2

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")


# ---------------- CONNECTION ----------------
def get_conn():
    return psycopg2.connect(
        DATABASE_URL,
        connect_timeout=5
    )


# ---------------- INIT TABLE ----------------
def init_db():
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
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
def add_anime(user_id, anime_id, anime_name, alias, episode=0, status="watching"):
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO tracked_anime
                (user_id, anime_id, anime_name, alias, last_watched, last_notified, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, anime_id) DO NOTHING
            """, (user_id, anime_id, anime_name, alias, episode, episode, status))


# ---------------- UPDATE ----------------
def update_progress(user_id, anime_id, episode):
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE tracked_anime
                SET last_watched = %s, status = 'watching'
                WHERE user_id = %s AND anime_id = %s
            """, (episode, user_id, anime_id))


def update_status(user_id, anime_id, status):
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE tracked_anime
                SET status = %s
                WHERE user_id = %s AND anime_id = %s
            """, (status, user_id, anime_id))


def update_last_notified(user_id, anime_id, episode):
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE tracked_anime
                SET last_notified = %s
                WHERE user_id = %s AND anime_id = %s
            """, (episode, user_id, anime_id))


def update_alias(user_id, anime_id, new_alias):
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE tracked_anime
                SET alias = %s
                WHERE user_id = %s AND anime_id = %s
            """, (new_alias, user_id, anime_id))


# ---------------- GET ----------------
def get_progress(user_id, identifier):
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT anime_name, alias, last_watched, anime_id, status
                FROM tracked_anime
                WHERE user_id = %s
                  AND (alias = %s OR anime_name = %s)
            """, (user_id, identifier, identifier))
            return cursor.fetchone()


def list_tracked(user_id):
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT anime_name, alias, last_watched, status
                FROM tracked_anime
                WHERE user_id = %s
                ORDER BY anime_name
            """, (user_id,))
            return cursor.fetchall()


def get_aliases(user_id):
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT alias FROM tracked_anime WHERE user_id = %s",
                (user_id,)
            )
            return [r[0] for r in cursor.fetchall()]


def get_all_tracked():
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT user_id, anime_id, last_watched, last_notified
                FROM tracked_anime
            """)
            return cursor.fetchall()


# ---------------- DELETE ----------------
def remove_anime(user_id, anime_id):
    with get_conn() as conn:
        with conn.cursor() as cursor:
            cursor.execute("""
                DELETE FROM tracked_anime
                WHERE user_id = %s AND anime_id = %s
            """, (user_id, anime_id))
