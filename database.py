import sqlite3
import os

os.makedirs("data", exist_ok=True)
conn = sqlite3.connect("data/tracker.db")
cursor = conn.cursor()

# ---------------- TABLE ----------------
cursor.execute("""
CREATE TABLE IF NOT EXISTS tracked_anime (
    user_id INTEGER,
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

# ---------------- ADD ----------------
def add_anime(user_id, anime_id, anime_name, alias, episode=0, status="watching"):
    cursor.execute("""
    INSERT OR IGNORE INTO tracked_anime
    (user_id, anime_id, anime_name, alias, last_watched, last_notified, status)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (user_id, anime_id, anime_name, alias, episode, episode, status))
    conn.commit()

# ---------------- UPDATE ----------------
def update_progress(user_id, anime_id, episode):
    cursor.execute("""
    UPDATE tracked_anime
    SET last_watched = ?, status = 'watching'
    WHERE user_id = ? AND anime_id = ?
    """, (episode, user_id, anime_id))
    conn.commit()

def update_status(user_id, anime_id, status):
    cursor.execute("""
    UPDATE tracked_anime
    SET status = ?
    WHERE user_id = ? AND anime_id = ?
    """, (status, user_id, anime_id))
    conn.commit()

def update_last_notified(user_id, anime_id, episode):
    cursor.execute("""
    UPDATE tracked_anime
    SET last_notified = ?
    WHERE user_id = ? AND anime_id = ?
    """, (episode, user_id, anime_id))
    conn.commit()

# ---------------- GET ----------------
def get_progress(user_id, identifier):
    cursor.execute("""
    SELECT anime_name, alias, last_watched, anime_id, status
    FROM tracked_anime
    WHERE user_id = ?
      AND (alias = ? OR anime_name = ?)
    """, (user_id, identifier, identifier))
    return cursor.fetchone()

def list_tracked(user_id):
    cursor.execute("""
    SELECT anime_name, alias, last_watched, status
    FROM tracked_anime
    WHERE user_id = ?
    ORDER BY anime_name
    """, (user_id,))
    return cursor.fetchall()

def get_aliases(user_id):
    cursor.execute(
        "SELECT alias FROM tracked_anime WHERE user_id = ?",
        (user_id,)
    )
    return [r[0] for r in cursor.fetchall()]

def get_all_tracked():
    cursor.execute("""
    SELECT user_id, anime_id, last_watched, last_notified
    FROM tracked_anime
    """)
    return cursor.fetchall()

# ---------------- DELETE ----------------
def remove_anime(user_id, anime_id):
    cursor.execute("""
    DELETE FROM tracked_anime
    WHERE user_id = ? AND anime_id = ?
    """, (user_id, anime_id))
    conn.commit()

# ---------------- ALIAS ----------------
def update_alias(user_id, anime_id, new_alias):
    cursor.execute("""
    UPDATE tracked_anime
    SET alias = ?
    WHERE user_id = ? AND anime_id = ?
    """, (new_alias, user_id, anime_id))
    conn.commit()

add_anime(391512501386477578, 12971, "Jujutsu Kaisen", "JK", 0, "watched")
add_anime(1028475649406550067, 140184, "Otonari no Tenshi-sama ni Itsunomanika Dame Ningen ni Sareteita Ken", "ONTNIDNNSK", 0, "want_to_watch")