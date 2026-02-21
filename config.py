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

USERS_FILE = "users.json"
DB_FILE = "production.db"
MIN_SLEEP = 28 * 60  # 28 minutes
MAX_SLEEP = 32 * 60  # 32 minutes

bot = telebot.TeleBot(TOKEN)

# User data storage (in-memory for conversation steps)
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
