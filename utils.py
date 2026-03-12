import re
import hashlib
from datetime import datetime, timedelta
from telebot import types
from config import logger, CITIES

# --- Helper Functions ---
# Pre-defined keywords that users can easily add
COMMON_KEYWORDS = [
    "תיווך", "שותפים", "סאבלט", "טווח קצר", "ללא תיווך", "יחידת דיור", "מרתף", "סטודיו"
]

COMMON_NEIGHBORHOODS = [
    "פלורנטין", "הצפון הישן", "לב העיר", "הצפון החדש", "נווה צדק", "בבלי"
]

# --- Content Deduplication ---
def generate_post_hash(text):
    """Returns an MD5 hash of cleaned post text for content-based deduplication."""
    if text is None:
        import random, string
        return ''.join(random.choices(string.ascii_letters + string.digits, k=32))
    cleaned = re.sub(r'\W+', '', text)
    return hashlib.md5(cleaned.encode('utf-8')).hexdigest()


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
        # "לפני X שעות" / "לפני שעה" → today
        if "לפני" in clean_text and ("שעה" in clean_text or "שעות" in clean_text or "דקות" in clean_text or "דקה" in clean_text or "יום" not in clean_text):
            return today
        
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


def parse_facebook_post(text):
    """Extracts rooms (float) and price (int) from a free-text Hebrew Facebook post."""
    if not text:
        return None

    # 1. Clean: remove commas, currency symbols, and Facebook invisible unicode
    clean_text = text.replace(',', '').replace('\u20aa', '').replace('\u05e9"\u05d7', '')
    clean_text = re.sub(r'[\u200B-\u200D\uFEFF\u200E\u200F\xa0]', ' ', clean_text)

    # 1b. Skip posts where the user is LOOKING for an apartment (Seeking)
    if re.search(r"\b(מחפש|מחפשת|מחפשים|דרושה|דרוש|מחפש/ת)\b", clean_text) and "להשכרה" not in clean_text[:30]:
        # If "להשכרה" is at the very start, it's likely an ad. Otherwise, "מחפש" usually means seeking.
        if not re.search(r"(?:מציע|מציעה|להשכרה|דירה להשכרה)", clean_text[:50]):
            return None

    rooms = None
    price = None

    try:
        # 2. Extract Rooms (e.g., "3 חדרים", "2.5 חד'", "4 ח", "3 חדרי שינה", "דירת 4.5 ענקית")
        # Pattern covers number + optional adjective + room label
        rooms_match = re.search(r"(\d{1,2}(?:\.\d)?)\s*(?:[^\w\s]{0,3}\s*(?:\w+\s+){0,2})?(?:חדרים|חדר|חדרי|חד'|חד\b|ח\b)", clean_text)
        if not rooms_match:
            # Fallback: "דירת 4 חדרים" or "דירת 4"
            rooms_match = re.search(r"דירת\s*(\d{1,2}(?:\.\d)?)", clean_text)
        
        if rooms_match:
            try:
                rooms = float(rooms_match.group(1))
            except ValueError:
                pass
        else:
            # Fallback for Hebrew number words (e.g., "דירת שני חדרים")
            hebrew_numbers = {
                'שני': 2.0, 'שתי': 2.0,
                'שלושה': 3.0, 'שלוש': 3.0,
                'ארבעה': 4.0, 'ארבע': 4.0,
                'חמישה': 5.0, 'חמש': 5.0,
                'שישה': 6.0, 'שש': 6.0,
            }
            for word, num in hebrew_numbers.items():
                if re.search(rf"\b{word}\s+(?:חדרים|חד'|חד\b)", clean_text):
                    rooms = num
                    break

        # Special check for 1-room / studio / single room mentioned
        if not rooms:
            single_room_patterns = [
                r"\b(דירת חדר|סטודיו|חדר אחד|חדר להשכרה|חדר בודד|חדר פנוי|מתפנה חדר)\b",
                r"בדירת (?:\d|שני|שתי|שלוש|שלושה|ארבע|ארבעה) שותפים" # If it says "in a X roommate apt", it's usually 1 room
            ]
            if any(re.search(p, clean_text) for p in single_room_patterns):
                rooms = 1.0

        # 3. Extract Price
        # Strategy A: K notation (e.g., 5.5K -> 5500)
        k_match = re.search(r'(\d{1,2}(?:\.\d)?)\s*[kK\u05e7]', clean_text)
        if k_match:
            price = int(float(k_match.group(1)) * 1000)

        # Strategy B: "\u05d0\u05dc\u05e3" text (e.g., 5.5 \u05d0\u05dc\u05e3 -> 5500)
        elif not price:
            alef_match = re.search(r'(\d{1,2}(?:\.\d)?)\s*\u05d0\u05dc\u05e3', clean_text)
            if alef_match:
                price = int(float(alef_match.group(1)) * 1000)

        # Strategy C: Look for labels followed by numbers
        if not price:
            # Labels: מחיר, שכ"ד, שכירות, ₪, NIS
            label_match = re.search(r"(?:מחיר|שכ\"ד|שכד|שכירות|₪|NIS)[:\s\-]*(\d{4,5})", clean_text, re.IGNORECASE)
            if label_match:
                price = int(label_match.group(1))

        # Strategy D: First logical 4-5 digit rent price, skipping common years
        if not price:
            found_prices = re.findall(r'(?<!\d)(\d{4,5})(?!\d)', clean_text)
            for p in found_prices:
                val = int(p)
                if 2500 <= val <= 20000 and val not in (2024, 2025, 2026, 2027):
                    price = val
                    break

    except Exception as e:
        logger.error(f"Error parsing Facebook post: {e}")

    return {'rooms': rooms, 'price': price}


def format_apartment_message(parsed_data):
    """Formats the parsed data into a Hebrew Telegram message."""
    price_val = parsed_data.get('price')
    rooms_val = parsed_data.get('rooms')
    
    return f"""\u200F🏢 *דירה חדשה מפייסבוק!*

\u200F💰 *מחיר:* {price_val if price_val is not None else 'לא צוין'}
\u200F🛏️ *חדרים:* {rooms_val if rooms_val is not None else 'לא צוין'}

\u200F🔗 [לחץ למעבר לפוסט בפייסבוק]({parsed_data.get('url', '')})"""


def send_apartment_alert(chat_id, parsed_data, **kwargs):
    """Sends the formatted alert message with optional markup to the user."""
    message = format_apartment_message(parsed_data)
    
    reply_markup = kwargs.get('reply_markup')
    try:
        from config import bot
        bot.send_message(
            chat_id, 
            message, 
            parse_mode="Markdown", 
            disable_web_page_preview=True,
            reply_markup=reply_markup
        )
    except Exception as e:
        from config import logger
        logger.error(f"Failed to send Facebook alert to {chat_id}: {e}")

def contains_blocked_keywords(text, blocked_keywords_str):
    """Checks if any blocked keyword from a comma-separated string is in the text."""
    if not text or not blocked_keywords_str:
        return False
    
    clean_text = text.lower()
    keywords = [k.strip().lower() for k in blocked_keywords_str.split(',') if k.strip()]
    
    for kw in keywords:
        if kw in clean_text:
            return True
            
    return False

def get_cities_markup():
    markup = types.InlineKeyboardMarkup(row_width=2)
    buttons = [types.InlineKeyboardButton(city, callback_data=f"setup_city_{city}") for city in CITIES.keys()]
    markup.add(*buttons)
    return markup

def get_price_markup(step):
    """step can be 'min_price' or 'max_price'"""
    markup = types.InlineKeyboardMarkup(row_width=3)
    prices = [2500, 3000, 3500, 4000, 4500, 5000, 5500, 6000, 6500, 7000, 8000, 10000]
    buttons = [types.InlineKeyboardButton(f"{p} ₪", callback_data=f"setup_{step}_{p}") for p in prices]
    markup.add(*buttons)
    val = "0" if step == 'min_price' else "9999999"
    markup.add(types.InlineKeyboardButton("♾️ ללא הגבלה", callback_data=f"setup_{step}_{val}"))
    return markup

def get_rooms_markup(step):
    """step can be 'min_rooms' or 'max_rooms'"""
    markup = types.InlineKeyboardMarkup(row_width=3)
    rooms = [1, 1.5, 2, 2.5, 3, 3.5, 4, 4.5, 5]
    buttons = [types.InlineKeyboardButton(str(r), callback_data=f"setup_{step}_{r}") for r in rooms]
    markup.add(*buttons)
    val = "0" if step == 'min_rooms' else "99"
    markup.add(types.InlineKeyboardButton("♾️ ללא הגבלה", callback_data=f"setup_{step}_{val}"))
    return markup


def construct_url(config):
    """Constructs the Yad2 URL based on configuration dictionary."""
    base_url = "https://www.yad2.co.il/realestate/rent"
    city_name = config.get('city', 'תל אביב')
    city_code = CITIES.get(city_name, "5000")
    
    min_r = config.get('min_rooms', 1.5)
    max_r = config.get('max_rooms', 3)
    min_p = config.get('min_price', 5000)
    max_p = config.get('max_price', 6700)
    
    # Format limits gracefully for Yad2
    r_str = f"{min_r if min_r != 0 else ''}-{max_r if max_r != 99 else ''}"
    p_str = f"{min_p if min_p != 0 else ''}-{max_p if max_p != 9999999 else ''}"
    
    params = (
        f"city={city_code}&"
        f"rooms={r_str}&"
        f"price={p_str}&"
        f"order=1"
    )
    return f"{base_url}?{params}"

def get_keywords_markup(blocked_keywords_str):
    """Generates the interactive keywords inline keyboard."""
    markup = types.InlineKeyboardMarkup(row_width=2)
    current_kws = [k.strip() for k in blocked_keywords_str.split(',') if k.strip()]
    
    # Active keywords (Remove buttons)
    if current_kws:
        remove_btns = [types.InlineKeyboardButton(f"❌ {kw}", callback_data=f"kw_rm_{kw}") for kw in current_kws]
        for i in range(0, len(remove_btns), 2):
            markup.add(*remove_btns[i:i+2])
            
    # Suggestions (Add buttons)
    suggestions = [kw for kw in COMMON_KEYWORDS if kw not in current_kws]
    if suggestions:
        add_btns = [types.InlineKeyboardButton(f"➕ {kw}", callback_data=f"kw_add_{kw}") for kw in suggestions]
        for i in range(0, len(add_btns), 2):
            markup.add(*add_btns[i:i+2])
            
    # Bottom actions
    markup.add(types.InlineKeyboardButton("✏️ הוסף מילה חדשה", callback_data="kw_custom"))
    markup.add(types.InlineKeyboardButton("🔙 חזור", callback_data="menu_back"))
    
    return markup


def get_neighborhoods_markup(neighborhoods_str):
    """Generates the interactive neighborhoods inline keyboard."""
    markup = types.InlineKeyboardMarkup(row_width=2)
    current_nbs = [k.strip() for k in neighborhoods_str.split(',') if k.strip()]
    
    # Active neighborhoods (Remove buttons)
    if current_nbs:
        remove_btns = [types.InlineKeyboardButton(f"✔️ {nb}", callback_data=f"nb_rm_{nb}") for nb in current_nbs]
        for i in range(0, len(remove_btns), 2):
            markup.add(*remove_btns[i:i+2])
            
    # Suggestions (Add buttons)
    suggestions = [nb for nb in COMMON_NEIGHBORHOODS if nb not in current_nbs]
    if suggestions:
        add_btns = [types.InlineKeyboardButton(f"➕ {nb}", callback_data=f"nb_add_{nb}") for nb in suggestions]
        for i in range(0, len(add_btns), 2):
            markup.add(*add_btns[i:i+2])
            
    # Bottom actions
    markup.add(types.InlineKeyboardButton("✏️ הוסף שכונה בטקסט", callback_data="nb_custom"))
    markup.add(types.InlineKeyboardButton("🔙 חזור", callback_data="menu_back"))
    
    return markup


def get_main_menu(is_active=True):
    """Returns the new inline main menu for the unified dashboard."""
    markup = types.InlineKeyboardMarkup(row_width=2)
    btn_edit = types.InlineKeyboardButton("🔍 ערוך מסננים", callback_data="menu_edit")
    btn_keys = types.InlineKeyboardButton("🚫 מילים חסומות", callback_data="kw_menu")
    btn_hood = types.InlineKeyboardButton("🏙️ מיין שכונות", callback_data="nb_menu")
    btn_saved = types.InlineKeyboardButton("⭐ דירות שמורות", callback_data="menu_saved_0")
    
    toggle_text = "⏸️ השהה עידכונים" if is_active else "▶️ חדש עידכונים"
    btn_toggle = types.InlineKeyboardButton(toggle_text, callback_data="menu_toggle")
    btn_delete = types.InlineKeyboardButton("🗑️ מחק חשבון", callback_data="confirm_delete_prompt")

    markup.add(btn_edit)
    markup.add(btn_keys)
    markup.add(btn_hood)
    markup.add(btn_saved)
    markup.add(btn_toggle)
    markup.add(btn_delete)
    return markup

def get_saved_apartments_display(saved_list, page=0):
    """Generates a text block and paginated inline keyboard for saved properties."""
    markup = types.InlineKeyboardMarkup(row_width=5)
    
    ITEMS_PER_PAGE = 5
    total_items = len(saved_list)
    start_idx = page * ITEMS_PER_PAGE
    end_idx = min(start_idx + ITEMS_PER_PAGE, total_items)
    
    if not saved_list:
        text = "\u200F⭐ *אין לך עדיין דירות שמורות.*\n\n\u200Fכשיגיעו התראות חדשות, תוכל ללחוץ על '⭐ שמור דירה' למטה."
        markup.add(types.InlineKeyboardButton("🔙 חזור להתחלה", callback_data="menu_back"))
        return text, markup
        
    # Render visible items as text
    text_lines = [f"\u200F⭐ *הדירות השמורות שלך* (עמוד {page + 1}):\n"]
    
    rm_btns = []
    
    for i, item in enumerate(saved_list[start_idx:end_idx]):
        idx = i + 1
        # Number emoji mapping for visual flair
        num_emoji = ["1️⃣", "2️⃣", "3️⃣", "4️⃣", "5️⃣"][i]
        
        # Clean up title
        short_title = item['title'].strip()
        if not short_title or short_title == "דירה שמורה":
            short_title = f"דירה שמורה {item['ad_id'][:6]}"
            
        text_lines.append(f"\u200F{num_emoji} [{short_title}]({item['url']}) - {item['price']}")
        rm_btns.append(types.InlineKeyboardButton(f"❌ מחק {idx}", callback_data=f"rm_ad_{item['ad_id']}_{page}"))
        
    text_lines.append(f"\n\u200Fיש לך {total_items} דירות שמורות בזיכרון.")
    text = "\n".join(text_lines)
    
    # Add compact remove buttons row
    if rm_btns:
        markup.add(*rm_btns)
        
    # Pagination controls
    nav_btns = []
    if page > 0:
        nav_btns.append(types.InlineKeyboardButton("⬅️ קודם", callback_data=f"menu_saved_{page-1}"))
    if end_idx < total_items:
        nav_btns.append(types.InlineKeyboardButton("הבא ➡️", callback_data=f"menu_saved_{page+1}"))
        
    if nav_btns:
        markup.add(*nav_btns)
        
    # Back button
    markup.add(types.InlineKeyboardButton("🔙 חזור להתחלה", callback_data="menu_back"))
    
    return text, markup

def satisfies_neighborhood_filter(text, neighborhoods_str):
    """
    Returns True if neighborhoods_str is empty.
    Else returns True only if at least one selected neighborhood is present in the text.
    """
    if not neighborhoods_str:
        return True
    
    nbs = [k.strip().lower() for k in neighborhoods_str.split(',') if k.strip()]
    if not nbs:
        return True
        
    clean_text = text.lower()
    for nb in nbs:
        if nb in clean_text:
            return True
        # Hebrew prefix handling: if neighborhood starts with "ה" (the), also check without it
        if nb.startswith("ה") and len(nb) > 2:
            no_he = nb[1:]
            if no_he in clean_text:
                return True
                
    return False

