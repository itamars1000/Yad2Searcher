import os
import logging
import telebot
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
logger = logging.getLogger("yad2bot")

# --- Configuration ---
TOKEN = os.getenv("TELEGRAM_TOKEN")
if not TOKEN:
    raise ValueError("No TELEGRAM_TOKEN found in environment variables")

APIFY_TOKEN = os.getenv("APIFY_TOKEN")
if not APIFY_TOKEN:
    raise ValueError("No APIFY_TOKEN found in environment variables")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    logger.warning("GEMINI_API_KEY not found. AI parsing will fail if called.")

ENABLE_FACEBOOK_SCRAPER = True # Set to True to enable Facebook scraping (consumes Apify API credits)

ADMIN_CHAT_ID = os.getenv("ADMIN_CHAT_ID")  # Your personal Telegram Chat ID (set in .env)

PAYBOX_LINK = os.getenv("PAYBOX_LINK", "https://payboxapp.page.link/YOUR_LINK_HERE")

USERS_FILE = "users.json"
DB_FILE = "production.db"
MIN_SLEEP = 28 * 60  # 28 minutes
MAX_SLEEP = 32 * 60  # 32 minutes

FB_MIN_SLEEP = 58 * 60  # 58 minutes
FB_MAX_SLEEP = 62 * 60  # 62 minutes

# Single broad URL for Smart Batching: all Tel Aviv, newest first, no price/rooms filter
# Individual per-user price/rooms filters are applied in code after scraping.
MASTER_SCRAPE_URL = "https://www.yad2.co.il/realestate/rent?city=5000&order=1"

bot = telebot.TeleBot(TOKEN)

# User data storage (in-memory for conversation steps)
user_data = {}

# --- Facebook Groups Scraping ---
FACEBOOK_GROUPS = [
    "https://www.facebook.com/groups/457465901082882?locale=he_IL",
    "https://www.facebook.com/groups/333022240594651?locale=he_IL",
    "https://www.facebook.com/groups/101875683484689?locale=he_IL",
    "https://www.facebook.com/groups/305724686290054/?locale=he_IL",
    "https://www.facebook.com/groups/968184269974550/?locale=he_IL",
]

APIFY_ACTOR_URL = "https://api.apify.com/v2/acts/apify~facebook-groups-scraper/runs"

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
