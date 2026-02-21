import os
import json
import sqlite3
from config import DB_FILE, USERS_FILE, logger

# --- Database Management ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS notifications (ad_id TEXT, user_id TEXT, PRIMARY KEY (ad_id, user_id))")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            url TEXT NOT NULL,
            active INTEGER DEFAULT 1
        )
    """)
    conn.commit()
    
    # Auto-migrate from users.json if it exists
    if os.path.exists(USERS_FILE):
        try:
            with open(USERS_FILE, "r", encoding="utf-8") as f:
                json_users = json.load(f)
            for uid, val in json_users.items():
                url = val if isinstance(val, str) else val.get("url", "")
                active = True if isinstance(val, str) else val.get("active", True)
                cursor.execute(
                    "INSERT OR IGNORE INTO users (user_id, url, active) VALUES (?, ?, ?)",
                    (str(uid), url, 1 if active else 0)
                )
            conn.commit()
            os.rename(USERS_FILE, USERS_FILE + ".bak")
            logger.info(f"Migrated {len(json_users)} users from users.json to DB. Old file renamed to users.json.bak")
        except Exception as e:
            logger.error(f"Error migrating users.json: {e}")
    
    conn.close()

def is_ad_notified(ad_id, user_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM notifications WHERE ad_id = ? AND user_id = ?", (ad_id, str(user_id)))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists

def mark_ad_notified(ad_id, user_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO notifications (ad_id, user_id) VALUES (?, ?)", (ad_id, str(user_id)))
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    conn.close()

# --- User Management (SQLite) ---
def load_users():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, url, active FROM users")
    rows = cursor.fetchall()
    conn.close()
    return {row[0]: {"url": row[1], "active": bool(row[2])} for row in rows}

def add_user(chat_id, url):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO users (user_id, url, active) VALUES (?, ?, 1)",
        (str(chat_id), url)
    )
    conn.commit()
    conn.close()

def set_user_active(chat_id, active):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET active = ? WHERE user_id = ?",
        (1 if active else 0, str(chat_id))
    )
    changed = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return changed

def remove_user(chat_id):
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE user_id = ?", (str(chat_id),))
    changed = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return changed
