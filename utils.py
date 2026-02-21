import re
from datetime import datetime, timedelta
from telebot import types
from config import logger

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
        match = re.search(r"(\d{1,2})[\/\.](\d{1,2})(?:[\/\.](\d{2,4}))?", clean_text)
        if match:
            day = int(match.group(1))
            month = int(match.group(2))
            year_group = match.group(3)

            if year_group:
                year = int(year_group)
                if year < 100:
                    year += 2000
            else:
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
        f"price={config.get('min_price', 5000)}-{config.get('max_price', 6700)}&"
        f"order=1"
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
