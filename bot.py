from config import bot, user_data, CITIES, logger
from database import add_user, set_user_active
from utils import construct_url, get_main_menu
from telebot import types

# --- Telegram Bot Handlers ---

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

    if max_rooms < min_rooms:
        max_rooms, min_rooms = min_rooms, max_rooms
        user_data[chat_id]['min_rooms'] = min_rooms
        bot.send_message(chat_id, f"🔄 הפכתי בין מינימום למקסימום חדרים: {min_rooms} - {max_rooms}")

    user_data[chat_id]['max_rooms'] = max_rooms
    
    config = {
        "city_code": user_data[chat_id]['city_code'],
        "min_price": user_data[chat_id]['min_price'],
        "max_price": user_data[chat_id]['max_price'],
        "min_rooms": user_data[chat_id]['min_rooms'],
        "max_rooms": user_data[chat_id]['max_rooms']
    }
    
    generated_url = construct_url(config)
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
