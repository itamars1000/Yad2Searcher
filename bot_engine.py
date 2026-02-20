import os
import json
import time
import random
import threading
import sqlite3
import logging
import requests
import telebot
from telebot import types
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth
import re
from datetime import datetime, timedelta
from dotenv import load_dotenv

load_dotenv()

# --- Logging Setup ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s | %(levelname)s | %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.FileHandler('bot.log', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)

# --- Configuration ---
# --- Configuration ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise ValueError("No TELEGRAM_TOKEN found in environment variables")
USERS_FILE = "users.json"
DB_FILE = "production.db"
MIN_SLEEP = 28 * 60  # 10 minutes
MAX_SLEEP = 32 * 60  # 14 minutes

bot = telebot.TeleBot(TOKEN)

# User data storage (in-memory for simplicity)
user_data = {}

# City codes mapping
CITIES = {
    "תל אביב": "5000",
    "רמת גן": "6600",
    "גבעתיים": "6300",
    "הרצליה": "6400",
    "חיפה": "4000",
    "ירושלים": "3000",
    "ראשון לציון": "8300"
}

# --- Helper Functions ---
def parse_hebrew_date(date_text):
    """Parses Hebrew/Relative dates from Yad2."""
    if not date_text:
        return None
    
    try:
        today = datetime.now().date()
        clean_text = date_text.strip()
        
        # 1. Relative Dates
        if any(x in clean_text for x in ["עודכן היום", "הוקפץ היום", "היום"]):
            return today
        if "אתמול" in clean_text:
            return today - timedelta(days=1)
        
        # 2. Standard Date Formats (DD/MM/YYYY or DD/MM/YY)
        # Regex to find date pattern (supports / or .)
        # User specified format: dd/mm/yy -> 2 digits year
        match = re.search(r"(\d{1,2})[\/\.](\d{1,2})(?:[\/\.](\d{2,4}))?", clean_text)
        if match:
            day = int(match.group(1))
            month = int(match.group(2))
            year_group = match.group(3)

            if year_group:
                year = int(year_group)
                # Handle 2-digit year (e.g., 26 -> 2026)
                if year < 100:
                    year += 2000
            else:
                # No year? Assume current year
                year = today.year
            
            return datetime(year, month, day).date()
            
    except Exception as e:
        logger.error(f"Error parsing date '{date_text}': {e}")
        return None
        
    return None

def construct_url(config):
    """Constructs the Yad2 URL based on configuration dictionary."""
    base_url = "https://www.yad2.co.il/realestate/rent"
    params = (
        f"city={config.get('city_code', '5000')}&"
        f"rooms={config.get('min_rooms', 1.5)}-{config.get('max_rooms', 3)}&"
        f"price={config.get('min_price', 5000)}-{config.get('max_price', 6700)}"
    )
    return f"{base_url}?{params}"

def get_main_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn_start = types.KeyboardButton("✅ הפעל התראות")
    btn_stop = types.KeyboardButton("🛑 עצור התראות")
    btn_new_filter = types.KeyboardButton("🔍 מסנן חדש")
    markup.add(btn_start, btn_stop)
    markup.add(btn_new_filter)
    return markup

# --- Database Management ---
def init_db():
    conn = sqlite3.connect(DB_FILE)
    cursor = conn.cursor()
    cursor.execute("CREATE TABLE IF NOT EXISTS notifications (ad_id TEXT, user_id TEXT, PRIMARY KEY (ad_id, user_id))")
    conn.commit()
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

# --- User Management ---
def load_users():
    if not os.path.exists(USERS_FILE):
        return {}
    try:
        with open(USERS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            
            # Migration: Convert old format (chat_id: url_string) to new format (chat_id: dict)
            migrated = False
            for uid, val in data.items():
                if isinstance(val, str):
                    data[uid] = {"url": val, "active": True}
                    migrated = True
            
            if migrated:
                save_users(data)
                logger.info("Migrated users.json to new schema.")
                
            return data
    except Exception as e:
        logger.error(f"Error loading users: {e}")
        return {}

def save_users(users):
    with open(USERS_FILE, "w", encoding="utf-8") as f:
        json.dump(users, f, indent=4)

def add_user(chat_id, url):
    users = load_users()
    users[str(chat_id)] = {"url": url, "active": True}
    save_users(users)

def set_user_active(chat_id, active):
    users = load_users()
    if str(chat_id) in users:
        users[str(chat_id)]["active"] = active
        save_users(users)
        return True
    return False

def remove_user(chat_id): # Still keeps 'remove' logic for /stop if needed, or we can repurpose to just disable
    users = load_users()
    if str(chat_id) in users:
        del users[str(chat_id)]
        save_users(users)
        return True
    return False

# --- Telegram Bot Logic ---
@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    """Entry point: Show welcome message with Start button."""
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True)
    btn_lets_go = types.KeyboardButton("🚀 התחל חיפוש")
    markup.add(btn_lets_go)
    
    welcome_text = (
        "👋 **ברוכים הבאים לבוט חיפוש הדירות שלכם!** 🏠\n\n"
        "אני כאן כדי לעזור לך למצוא את הדירה המושלמת במהירות.\n"
        "🤖 **מה אני יודע לעשות?**\n"
        "1. לסרוק את יד2 עבורך כל כמה דקות.\n"
        "2. לסנן מודעות ישנות ולוודא שאתה מקבל רק דברים שהועלו **היום**.\n"
        "3. לשלוח לך התראה מיידית לטלגרם ברגע שיש מציאה!\n\n"
        "מוכנים להתחיל?"
    )
    
    bot.reply_to(message, welcome_text, reply_markup=markup, parse_mode="Markdown")

@bot.message_handler(func=lambda message: message.text == "🚀 התחל חיפוש")
def show_city_selection(message):
    """Step 2: Select a city."""
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = []
    for city_name, city_code in CITIES.items():
        buttons.append(types.InlineKeyboardButton(city_name, callback_data=f"city_{city_code}_{city_name}"))
    markup.add(*buttons)
    
    bot.reply_to(message, 
                 "מעולה! בוא נגדיר את החיפוש.\n\n👇 **באיזו עיר תרצו לחפש?**", 
                 reply_markup=markup)

@bot.message_handler(func=lambda message: message.text == "✅ הפעל התראות")
def enable_notifications(message):
    if set_user_active(message.chat.id, True):
        bot.reply_to(message, "✅ ההתראות הופעלו! נמשיך לחפש עבורך.", reply_markup=get_main_menu())
    else:
        bot.reply_to(message, "⚠️ לא מצאתי הגדרות עבורך. אנא התחל עם /start")

@bot.message_handler(func=lambda message: message.text == "🛑 עצור התראות")
def disable_notifications(message):
    if set_user_active(message.chat.id, False):
        bot.reply_to(message, "🛑 ההתראות הופסקו. (ההגדרות שלך נשמרו, תוכל להפעיל מחדש בכל רגע)", reply_markup=get_main_menu())
    else:
        bot.reply_to(message, "⚠️ לא מצאתי הגדרות עבורך. אנא התחל עם /start")

@bot.message_handler(func=lambda message: message.text == "🔍 מסנן חדש")
def new_filter_request(message):
    show_city_selection(message)

@bot.message_handler(commands=['stop'])
def stop_notifications_command(message):
    disable_notifications(message)

@bot.callback_query_handler(func=lambda call: call.data.startswith('city_'))
def callback_city(call):
    """Handle city selection."""
    _, city_code, city_name = call.data.split('_')
    chat_id = call.message.chat.id
    user_data[chat_id] = {'city_code': city_code, 'city_name': city_name}
    
    bot.answer_callback_query(call.id)
    msg = bot.send_message(chat_id, f"✅ נבחרה העיר: {city_name}\n\nמה המחיר **המינימלי** בשקלים? (למשל: 3000)", parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_min_price_step)

def process_min_price_step(message):
    chat_id = message.chat.id
    if not message.text.isdigit():
        msg = bot.reply_to(message, "⚠️ המחיר חייב להיות מספר שלם (למשל: 3000). נסה שוב:")
        bot.register_next_step_handler(msg, process_min_price_step)
        return

    min_price = int(message.text)
    user_data[chat_id]['min_price'] = min_price
    
    msg = bot.send_message(chat_id, "מה המחיר **המקסימלי** בשקלים? (למשל: 6000)", parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_max_price_step)

def process_max_price_step(message):
    chat_id = message.chat.id
    if not message.text.isdigit():
        msg = bot.reply_to(message, "⚠️ המחיר חייב להיות מספר שלם (למשל: 6000). נסה שוב:")
        bot.register_next_step_handler(msg, process_max_price_step)
        return

    max_price = int(message.text)
    min_price = user_data[chat_id]['min_price']

    # Sanity Check: Swap if max < min
    if max_price < min_price:
        max_price, min_price = min_price, max_price
        user_data[chat_id]['min_price'] = min_price
        bot.send_message(chat_id, f"🔄 שמתי לב שהמקסימום נמוך מהמינימום, אז הפכתי ביניהם: {min_price} - {max_price} ₪")

    user_data[chat_id]['max_price'] = max_price
    
    msg = bot.send_message(chat_id, "מה **מינימום** החדרים? (למשל: 2 או 2.5)", parse_mode="Markdown")
    bot.register_next_step_handler(msg, process_min_rooms_step)

def process_min_rooms_step(message):
    chat_id = message.chat.id
    try:
        min_rooms = float(message.text)
        user_data[chat_id]['min_rooms'] = min_rooms
        
        msg = bot.send_message(chat_id, "מה **מקסימום** החדרים? (למשל: 3.5 או 4)", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_max_rooms_step)
    except ValueError:
        msg = bot.reply_to(message, "⚠️ נא להקליד מספר (אפשר עשרוני, למשל: 2.5). נסה שוב:")
        bot.register_next_step_handler(msg, process_min_rooms_step)

def process_max_rooms_step(message):
    chat_id = message.chat.id
    try:
        max_rooms = float(message.text)
    except ValueError:
        msg = bot.reply_to(message, "⚠️ נא להקליד מספר (אפשר עשרוני). נסה שוב:")
        bot.register_next_step_handler(msg, process_max_rooms_step)
        return

    min_rooms = user_data[chat_id]['min_rooms']

    # Sanity Check: Swap if max < min
    if max_rooms < min_rooms:
        max_rooms, min_rooms = min_rooms, max_rooms
        user_data[chat_id]['min_rooms'] = min_rooms
        bot.send_message(chat_id, f"🔄 הפכתי בין מינימום למקסימום חדרים: {min_rooms} - {max_rooms}")

    user_data[chat_id]['max_rooms'] = max_rooms
    
    # Construct parameters for URL generation
    config = {
        "city_code": user_data[chat_id]['city_code'],
        "min_price": user_data[chat_id]['min_price'],
        "max_price": user_data[chat_id]['max_price'],
        "min_rooms": user_data[chat_id]['min_rooms'],
        "max_rooms": user_data[chat_id]['max_rooms']
    }
    
    # Generate URL
    generated_url = construct_url(config)
    
    # Save to users.json (mapped to chat_id)
    add_user(chat_id, generated_url)
    
    city_name = user_data[chat_id]['city_name']
    bot.send_message(chat_id, 
                        f"🎉 **ההגדרות עודכנו בהצלחה!**\n\n"
                        f"🏙️ עיר: {city_name}\n"
                        f"💰 מחיר: {config['min_price']} - {config['max_price']} ₪\n"
                        f"🛏️ חדרים: {config['min_rooms']} - {config['max_rooms']}\n\n"
                        f"הבוט יתחיל לסרוק עבורך!",
                        parse_mode="Markdown",
                        reply_markup=get_main_menu())

def run_bot():
    logger.info("Bot started...")
    bot.infinity_polling()

# --- Scraper Logic ---
def extract_ad_id(link):
    try:
        path = urlparse(link).path
        if "/item/" in path:
            return path.split("/item/")[-1]
        return None
    except:
        return None

def scrape_cycle():
    logger.info("--- Starting Scraper Cycle ---")
    users = load_users()
    
    if not users:
        logger.info("No users configured.")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        
        for user_id, user_data in users.items():
            # Handle both old (string) and new (dict) formats gracefully during runtime migration overlap
            if isinstance(user_data, str):
                search_url = user_data
                active = True
            else:
                search_url = user_data.get("url")
                active = user_data.get("active", True)
            
            if not active:
                logger.info(f"User {user_id} notifications disabled. Skipping.")
                continue

            logger.info(f"Checking for user {user_id}...")
            
            # Stealth Context
            context = browser.new_context(
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/121.0.0.0 Safari/537.36",
                viewport={"width": random.randint(1800, 1920), "height": random.randint(900, 1080)},
                locale="he-IL"
            )
            page = context.new_page()
            stealth = Stealth()
            stealth.apply_stealth_sync(page)
            
            try:
                # Retry logic for page loading
                for attempt in range(3):
                    try:
                        page.goto(search_url, timeout=30000)
                        break
                    except Exception as e:
                        if attempt < 2:
                            logger.warning(f"Page load attempt {attempt+1} failed for user {user_id}: {e}. Retrying in 10s...")
                            time.sleep(10)
                        else:
                            raise
                
                time.sleep(5) # Initial load
                page.mouse.wheel(0, 1000) # Trigger lazy load
                time.sleep(3)
                
                # Check for feed items
                items = page.locator("li[data-nagish='feed-item-list-box']").all()
                if not items:
                    items = page.locator(".feed-item").all() # Fallback selector
                
                logger.info(f"Found {len(items)} items in feed.")
                
                new_ads_count = 0
                already_notified_count = 0
                too_old_count = 0
                no_date_count = 0
                no_link_count = 0
                error_count = 0
                # Process top 15 items (sorted by newest first via order=1)
                for i, item in enumerate(items[:15]):
                    logger.debug(f"--- Processing Item {i+1}/{min(len(items), 15)} ---")
                    try:
                        # Extract Link
                        link_el = item.locator("a").first
                        if link_el.count() == 0:
                            logger.debug(f"Item {i}: No link element found. Skipping.")
                            no_link_count += 1
                            continue
                            
                        href = link_el.get_attribute("href")
                        if not href: 
                            logger.debug(f"Item {i}: No href attribute. Skipping.")
                            no_link_count += 1
                            continue
                        
                        full_link = f"https://www.yad2.co.il{href}" if href.startswith("/") else href
                        ad_id = extract_ad_id(full_link)
                         
                        if not ad_id: 
                            logger.debug(f"Item {i}: Could not extract Ad ID from {full_link}. Skipping.")
                            no_link_count += 1
                            continue
                        
                        
                        logger.debug(f"Item {i}: Ad ID {ad_id} found.")
                        
                        # Deduplication (Check EARLY)
                        if is_ad_notified(ad_id, user_id):
                            logger.debug(f"Ad {ad_id}: Already notified. Skipping.")
                            already_notified_count += 1
                            continue

                        # Extract Price early for logging
                        price = item.locator("[data-testid='price']").inner_text().strip() if item.locator("[data-testid='price']").count() else "N/A"

                        # --- Date Filtering (Strict Class Match) ---
                        try:
                            # 1. Target specific element: span[class*="report-ad_createdAt"]
                            # The user identified this specific class for the date.
                            date_el = item.locator('span[class*="report-ad_createdAt"]').first
                            
                            parsed_date = None
                            date_text_log = "N/A"

                            if date_el.count() > 0:
                                raw_text = date_el.inner_text()
                                date_text_log = raw_text
                                
                                # 2. Regex Extraction (dd/mm/yy)
                                # Look for 11/02/26 pattern
                                match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2})", raw_text)
                                if match:
                                    day = int(match.group(1))
                                    month = int(match.group(2))
                                    year_short = int(match.group(3))
                                    year_full = 2000 + year_short
                                    
                                    parsed_date = datetime(year_full, month, day).date()
                                    logger.debug(f"Item {i}: Parsed date {parsed_date} from '{raw_text}' (Regex).")
                                else:
                                    # Fallback: Check for "Today"/"Yesterday" if regex fails
                                    parsed_date = parse_hebrew_date(raw_text)
                                    logger.debug(f"Item {i}: Parsed date {parsed_date} from '{raw_text}' (Fallback).")
                            else:
                                # Fallback 2: Try extracting date from Image URL
                                # Image URL format: https://img.yad2.co.il/Pic/202602/02/...
                                img_el = item.locator("img").first
                                if img_el.count() > 0:
                                    src = img_el.get_attribute("src")
                                    if src:
                                        img_match = re.search(r"/Pic/(\d{4})(\d{2})/(\d{2})/", src)
                                        if img_match:
                                            y = int(img_match.group(1))
                                            m = int(img_match.group(2))
                                            d = int(img_match.group(3))
                                            parsed_date = datetime(y, m, d).date()
                                            logger.debug(f"Item {i}: Parsed date {parsed_date} from Image URL.")
                                
                                if not parsed_date:
                                    logger.debug(f"Item {i}: Date selector NOT found & Image URL failed.")
                                    # Try generic text search just in case
                                    # parsed_date = parse_hebrew_date(item.inner_text())
                                    pass
                            
                            # Log what we found
                            # print(f"Ad {ad_id} | Price: {price} | Date: {parsed_date} (Raw: {date_text_log})")

                            if not parsed_date:
                                # Skip if we can't find a valid date (Strict rule)
                                logger.debug(f"Ad {ad_id}: No valid date found. Skipping.")
                                no_date_count += 1
                                continue
                            
                            # 3. 7-Day Filter
                            today = datetime.now().date()
                            delta = (today - parsed_date).days
                            
                            logger.debug(f"Ad {ad_id} | Price: {price} | Date: {parsed_date} | Age: {delta} days")

                            if delta > 3:
                                # Skipping old ads (older than 3 days)
                                too_old_count += 1
                                continue
                            
                            # If we are here, ad is FRESH.

                        except Exception as e:
                            logger.error(f"Error checking date for {ad_id}: {e}")
                            error_count += 1
                            continue

                        # Deduplication check moved up
                        # New Ad Found! Extract Details
                        # Price already extracted above
                        address = item.locator("[data-testid='street-name']").inner_text().strip() if item.locator("[data-testid='street-name']").count() else ""
                        city = item.locator("[data-testid='item-info-line-1st']").inner_text().strip() if item.locator("[data-testid='item-info-line-1st']").count() else ""
                        rooms = item.locator("[data-testid='item-info-line-2nd']").inner_text().strip() if item.locator("[data-testid='item-info-line-2nd']").count() else ""

                        
                        msg = (
                            f"🏠 *מציאה חדשה!*\n"
                            f"📍 {address}, {city}\n"
                            f"💰 {price}\n"
                            f"🛏️ {rooms}\n"
                            f"🔗 [לצפייה במודעה]({full_link})"
                        )
                        
                        # Send Notification
                        logger.info(f"Sending notification to {user_id} for ad {ad_id}")
                        try:
                            bot.send_message(user_id, msg, parse_mode="Markdown")
                            mark_ad_notified(ad_id, user_id)
                            logger.info(f"Ad {ad_id} sent to user {user_id}.")
                            new_ads_count += 1
                        except Exception as e:
                            logger.error(f"Failed to send to {user_id}: {e}")
                            
                    except Exception as e:
                        logger.error(f"Error parsing item {i}: {e}")
                        error_count += 1
                
                processed = min(len(items), 15)
                logger.info(f"📊 Scan Summary for user {user_id}: "
                      f"Found {len(items)} items | "
                      f"Processed {processed} | "
                      f"{already_notified_count} already notified | "
                      f"{too_old_count} too old | "
                      f"{no_date_count} no date | "
                      f"{no_link_count} no link | "
                      f"{error_count} errors | "
                      f"{new_ads_count} NEW sent")
                
            except Exception as e:
                logger.error(f"Error scraping for user {user_id}: {e}")
            finally:
                context.close()
                time.sleep(random.randint(5, 10)) # Pause between users
        
        browser.close()

def run_scraper():
    while True:
        try:
            scrape_cycle()
        except Exception as e:
            logger.critical(f"Critical Scraper Error: {e}")
        
        sleep_time = random.randint(MIN_SLEEP, MAX_SLEEP)
        logger.info(f"Sleeping for {sleep_time // 60} minutes ({sleep_time}s)...")
        time.sleep(sleep_time)

# --- Main Engine ---
if __name__ == "__main__":
    init_db()
    
    # Thread 1: Telegram Bot
    t1 = threading.Thread(target=run_bot, daemon=True)
    t1.start()
    
    # Thread 2: Scraper Loop
    t2 = threading.Thread(target=run_scraper, daemon=True)
    t2.start()
    
    # Keep main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Stopping...")
