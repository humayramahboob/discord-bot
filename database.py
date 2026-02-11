import os
import psycopg2
from psycopg2.pool import SimpleConnectionPool

DATABASE_URL = os.getenv("DATABASE_URL")
if not DATABASE_URL:
    raise RuntimeError("DATABASE_URL is not set")

# ---------------- CONNECTION POOL ----------------
pool = SimpleConnectionPool(
    minconn=1,
    maxconn=10,   # adjust if needed (Render free tier should stay <=10)
    dsn=DATABASE_URL,
    connect_timeout=5
)

def get_conn():
    return pool.getconn()

def release_conn(conn):
    pool.putconn(conn)


# ---------------- INIT TABLE ----------------
def init_db():
    conn = get_conn()
    try:
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
        conn.commit()
    finally:
        release_conn(conn)


# ---------------- ADD ----------------
def add_anime(user_id, anime_id, anime_name, alias, episode=0, status="watching"):
    conn = get_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                INSERT INTO tracked_anime
                (user_id, anime_id, anime_name, alias, last_watched, last_notified, status)
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (user_id, anime_id) DO NOTHING
            """, (user_id, anime_id, anime_name, alias, episode, episode, status))
        conn.commit()
    finally:
        release_conn(conn)


# ---------------- UPDATE ----------------
def update_progress(user_id, anime_id, episode):
    conn = get_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE tracked_anime
                SET last_watched = %s, status = 'watching'
                WHERE user_id = %s AND anime_id = %s
            """, (episode, user_id, anime_id))
        conn.commit()
    finally:
        release_conn(conn)


def update_status(user_id, anime_id, status):
    conn = get_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE tracked_anime
                SET status = %s
                WHERE user_id = %s AND anime_id = %s
            """, (status, user_id, anime_id))
        conn.commit()
    finally:
        release_conn(conn)


def update_last_notified(user_id, anime_id, episode):
    conn = get_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE tracked_anime
                SET last_notified = %s
                WHERE user_id = %s AND anime_id = %s
            """, (episode, user_id, anime_id))
        conn.commit()
    finally:
        release_conn(conn)


def update_alias(user_id, anime_id, new_alias):
    conn = get_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                UPDATE tracked_anime
                SET alias = %s
                WHERE user_id = %s AND anime_id = %s
            """, (new_alias, user_id, anime_id))
        conn.commit()
    finally:
        release_conn(conn)


# ---------------- GET ----------------
def get_progress(user_id, identifier):
    conn = get_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT anime_name, alias, last_watched, anime_id, status
                FROM tracked_anime
                WHERE user_id = %s
                  AND (alias = %s OR anime_name = %s)
            """, (user_id, identifier, identifier))
            return cursor.fetchone()
    finally:
        release_conn(conn)


def list_tracked(user_id):
    conn = get_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT anime_name, alias, last_watched, status
                FROM tracked_anime
                WHERE user_id = %s
                ORDER BY anime_name
            """, (user_id,))
            return cursor.fetchall()
    finally:
        release_conn(conn)


def get_aliases(user_id):
    conn = get_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute(
                "SELECT alias FROM tracked_anime WHERE user_id = %s",
                (user_id,)
            )
            return [r[0] for r in cursor.fetchall()]
    finally:
        release_conn(conn)


def get_all_tracked():
    conn = get_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                SELECT user_id, anime_id, last_watched, last_notified
                FROM tracked_anime
            """)
            return cursor.fetchall()
    finally:
        release_conn(conn)


# ---------------- DELETE ----------------
def remove_anime(user_id, anime_id):
    conn = get_conn()
    try:
        with conn.cursor() as cursor:
            cursor.execute("""
                DELETE FROM tracked_anime
                WHERE user_id = %s AND anime_id = %s
            """, (user_id, anime_id))
        conn.commit()
    finally:
        release_conn(conn)