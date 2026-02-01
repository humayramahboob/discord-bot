import sqlite3
import psycopg2
import os

# ---------- SQLITE ----------
sqlite_conn = sqlite3.connect("tracker.db")
sqlite_cursor = sqlite_conn.cursor()

# ---------- POSTGRES ----------
POSTGRES_URL = os.getenv("DATABASE_URL")

if not POSTGRES_URL:
    raise Exception("DATABASE_URL not set")

pg_conn = psycopg2.connect(POSTGRES_URL)
pg_cursor = pg_conn.cursor()

# ---------- FETCH SQLITE DATA ----------
sqlite_cursor.execute("""
SELECT
    user_id,
    anime_id,
    anime_name,
    alias,
    last_watched,
    last_notified,
    status
FROM tracked_anime
""")

rows = sqlite_cursor.fetchall()
print(f"Found {len(rows)} rows in SQLite")

# ---------- INSERT INTO POSTGRES ----------
for row in rows:
    pg_cursor.execute("""
    INSERT INTO tracked_anime
    (user_id, anime_id, anime_name, alias, last_watched, last_notified, status)
    VALUES (%s, %s, %s, %s, %s, %s, %s)
    ON CONFLICT (user_id, anime_id) DO NOTHING
    """, row)

pg_conn.commit()

print("✅ Migration complete")

# ---------- CLEANUP ----------
sqlite_conn.close()
pg_conn.close()
