import os
import json
import sqlite3
from config import DB_FILE, USERS_FILE, logger

# --- Database Management ---
def init_db():
    conn = sqlite3.connect(DB_FILE, timeout=10.0)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS notifications (ad_id TEXT, user_id TEXT, PRIMARY KEY (ad_id, user_id))")
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id TEXT PRIMARY KEY,
            url TEXT NOT NULL,
            active INTEGER DEFAULT 1,
            keywords TEXT DEFAULT '',
            city TEXT DEFAULT 'תל אביב',
            neighborhoods TEXT DEFAULT ''
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS saved_apartments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id TEXT,
            ad_id TEXT,
            title TEXT,
            price TEXT,
            url TEXT,
            timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, ad_id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS invite_codes (
            code VARCHAR PRIMARY KEY,
            is_used BOOLEAN DEFAULT FALSE,
            used_by BIGINT NULL
        )
    """)
    conn.commit()
    
    # Run migration to add new columns if they don't exist
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN keywords TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass # Column might already exist
        
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN city TEXT DEFAULT 'תל אביב'")
    except sqlite3.OperationalError:
        pass # Column might already exist
        
    try:
        cursor.execute("ALTER TABLE users ADD COLUMN neighborhoods TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass # Column might already exist
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
                    "INSERT OR IGNORE INTO users (user_id, url, active, keywords, city, neighborhoods) VALUES (?, ?, ?, '', 'תל אביב', '')",
                    (str(uid), url, 1 if active else 0)
                )
            conn.commit()
            os.rename(USERS_FILE, USERS_FILE + ".bak")
            logger.info(f"Migrated {len(json_users)} users from users.json to DB. Old file renamed to users.json.bak")
        except Exception as e:
            logger.error(f"Error migrating users.json: {e}")
    
    conn.close()

def is_ad_notified(ad_id, user_id):
    conn = sqlite3.connect(DB_FILE, timeout=10.0)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM notifications WHERE ad_id = ? AND user_id = ?", (ad_id, str(user_id)))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists

def mark_ad_notified(ad_id, user_id):
    conn = sqlite3.connect(DB_FILE, timeout=10.0)
    cursor = conn.cursor()
    try:
        cursor.execute("INSERT INTO notifications (ad_id, user_id) VALUES (?, ?)", (ad_id, str(user_id)))
        conn.commit()
    except sqlite3.IntegrityError:
        pass
    conn.close()

# --- User Management (SQLite) ---
def load_users():
    conn = sqlite3.connect(DB_FILE, timeout=10.0)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id, url, active, keywords, city, neighborhoods FROM users")
    rows = cursor.fetchall()
    conn.close()
    return {row[0]: {"url": row[1], "active": bool(row[2]), "keywords": row[3], "city": row[4], "neighborhoods": row[5]} for row in rows}

def add_user(chat_id, url, keywords='', city='תל אביב', neighborhoods=''):
    conn = sqlite3.connect(DB_FILE, timeout=10.0)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR REPLACE INTO users (user_id, url, active, keywords, city, neighborhoods) VALUES (?, ?, 1, ?, ?, ?)",
        (str(chat_id), url, keywords, city, neighborhoods)
    )
    conn.commit()
    conn.close()

def update_user_keywords(chat_id, keywords):
    conn = sqlite3.connect(DB_FILE, timeout=10.0)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET keywords = ? WHERE user_id = ?",
        (keywords, str(chat_id))
    )
    changed = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return changed

def update_user_neighborhoods(chat_id, neighborhoods):
    conn = sqlite3.connect(DB_FILE, timeout=10.0)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET neighborhoods = ? WHERE user_id = ?",
        (neighborhoods, str(chat_id))
    )
    changed = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return changed

def update_user_city(chat_id, city):
    conn = sqlite3.connect(DB_FILE, timeout=10.0)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET city = ? WHERE user_id = ?",
        (city, str(chat_id))
    )
    changed = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return changed

def update_user_url(chat_id, url):
    conn = sqlite3.connect(DB_FILE, timeout=10.0)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET url = ? WHERE user_id = ?",
        (url, str(chat_id))
    )
    changed = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return changed

def set_user_active(chat_id, active):
    conn = sqlite3.connect(DB_FILE, timeout=10.0)
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE users SET active = ? WHERE user_id = ?",
        (1 if active else 0, str(chat_id))
    )
    conn.commit()
    conn.close()

# --- Saved Apartments Management ---
def save_apartment(user_id, ad_id, title, price, url):
    conn = sqlite3.connect(DB_FILE, timeout=10.0)
    cursor = conn.cursor()
    try:
        cursor.execute(
            "INSERT OR IGNORE INTO saved_apartments (user_id, ad_id, title, price, url) VALUES (?, ?, ?, ?, ?)",
            (str(user_id), str(ad_id), title, price, url)
        )
        conn.commit()
    except Exception as e:
        logger.error(f"Error saving apartment: {e}")
    finally:
        conn.close()

def remove_saved_apartment(user_id, ad_id):
    conn = sqlite3.connect(DB_FILE, timeout=10.0)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM saved_apartments WHERE user_id = ? AND ad_id = ?", (str(user_id), str(ad_id)))
    conn.commit()
    conn.close()

def get_saved_apartments(user_id):
    conn = sqlite3.connect(DB_FILE, timeout=10.0)
    cursor = conn.cursor()
    cursor.execute("SELECT ad_id, title, price, url FROM saved_apartments WHERE user_id = ? ORDER BY timestamp DESC", (str(user_id),))
    rows = cursor.fetchall()
    conn.close()
    return [{"ad_id": row[0], "title": row[1], "price": row[2], "url": row[3]} for row in rows]

def is_apartment_saved(user_id, ad_id):
    conn = sqlite3.connect(DB_FILE, timeout=10.0)
    cursor = conn.cursor()
    cursor.execute("SELECT 1 FROM saved_apartments WHERE user_id = ? AND ad_id = ?", (str(user_id), str(ad_id)))
    exists = cursor.fetchone() is not None
    conn.close()
    return exists

def remove_user(chat_id):
    conn = sqlite3.connect(DB_FILE, timeout=10.0)
    cursor = conn.cursor()
    cursor.execute("DELETE FROM users WHERE user_id = ?", (str(chat_id),))
    changed = cursor.rowcount > 0
    conn.commit()
    conn.close()
    return changed

# --- Invite Code Management ---
def create_invite_code(code: str):
    """Insert a new single-use invite code into the DB."""
    conn = sqlite3.connect(DB_FILE, timeout=10.0)
    cursor = conn.cursor()
    cursor.execute(
        "INSERT OR IGNORE INTO invite_codes (code, is_used, used_by) VALUES (?, FALSE, NULL)",
        (code,)
    )
    conn.commit()
    conn.close()

def validate_and_use_code(code: str, chat_id: int) -> bool:
    """
    Check if code exists and is unused. If valid, mark as used and return True.
    Returns False if the code doesn't exist or was already used.
    """
    conn = sqlite3.connect(DB_FILE, timeout=10.0)
    cursor = conn.cursor()
    cursor.execute(
        "SELECT is_used FROM invite_codes WHERE code = ?", (code,)
    )
    row = cursor.fetchone()
    if row is None or row[0]:
        conn.close()
        return False
    cursor.execute(
        "UPDATE invite_codes SET is_used = TRUE, used_by = ? WHERE code = ?",
        (chat_id, code)
    )
    conn.commit()
    conn.close()
    return True
