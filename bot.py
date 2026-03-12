import telebot
from telebot import types
import os
import re
from datetime import datetime

from config import bot, CITIES, logger, user_data, ADMIN_CHAT_ID
from database import load_users, add_user, update_user_keywords, update_user_neighborhoods, update_user_city, update_user_url, set_user_active, save_apartment, remove_saved_apartment, get_saved_apartments, is_apartment_saved, create_invite_code, validate_and_use_code, remove_user
from utils import construct_url, get_cities_markup, get_price_markup, get_rooms_markup, get_keywords_markup, get_neighborhoods_markup, get_main_menu, get_saved_apartments_display

# --- Telegram Bot Handlers ---

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    """Entry point: gate new users with invite code, show welcome to existing ones."""
    chat_id = message.chat.id
    users = load_users()

    if str(chat_id) not in users:
        # New user — require invite code
        user_data[chat_id] = {'awaiting_invite': True}
        bot.send_message(
            chat_id,
            "👋 *ברוכים הבאים לבוט חיפוש הדירות!* 🏠\n\n"
            "🔑 הבוט הזה פועל על בסיס הזמנה בלבד.\n"
            "אנא הזן את קוד הגישה שקיבלת:",
            parse_mode="Markdown"
        )
        return

    # Existing user → straight to setup wizard
    welcome_text = (
        "\u200F👋 *ברוכים הבאים לבוט חיפוש הדירות!* 🏠\n\n"
        "\u200Fכדי להתחיל לקבל התראות לדירות שמתאימות לך, לחץ על הכפתור למטה."
    )
    markup = types.InlineKeyboardMarkup()
    markup.add(types.InlineKeyboardButton("🎯 בחירת מסננים", callback_data="start_setup"))
    bot.send_message(chat_id, welcome_text, reply_markup=markup, parse_mode="Markdown")


# --- Invite Code Handlers ---

@bot.message_handler(commands=['invite'])
def handle_invite_command(message):
    """Admin-only: generate a new single-use invite code."""
    chat_id = message.chat.id
    if not ADMIN_CHAT_ID or str(chat_id) != str(ADMIN_CHAT_ID):
        bot.send_message(chat_id, "⛔ אין לך הרשאה לפקודה זו.")
        return

    import secrets, string
    code = ''.join(secrets.choice(string.ascii_uppercase + string.digits) for _ in range(6))
    create_invite_code(code)
    bot.send_message(chat_id, f"🔑 קוד גישה חדש נוצר: `{code}`", parse_mode="Markdown")
    logger.info(f"Admin generated invite code: {code}")


@bot.message_handler(func=lambda m: user_data.get(m.chat.id, {}).get('awaiting_invite'))
def verify_access_code(message):
    """Handle invite code entry for new users."""
    chat_id = message.chat.id
    code = message.text.strip()

    if validate_and_use_code(code, chat_id):
        # Code is valid — register the user and proceed
        user_data[chat_id].pop('awaiting_invite', None)
        add_user(chat_id, construct_url({'city': 'תל אביב'}))
        bot.send_message(chat_id, "✅ הקוד אומת בהצלחה! בואו נגדיר את החיפוש שלך.", parse_mode="Markdown")
        logger.info(f"New user {chat_id} joined with invite code {code}")
        # Trigger setup wizard
        markup = types.InlineKeyboardMarkup()
        markup.add(types.InlineKeyboardButton("🎯 בחירת מסננים", callback_data="start_setup"))
        bot.send_message(chat_id, "🏠 *מה תחומי החיפוש שלך?* לחץ למטה להתחלה:", reply_markup=markup, parse_mode="Markdown")
    else:
        bot.send_message(
            chat_id,
            "❌ קוד שגוי או שכבר נעשה בו שימוש.\n"
            "אנא ודא שהזנת את הקוד נכון, או פנה למנהל המערכת."
        )



# --- Delete Account ---

@bot.message_handler(commands=['delete'])
def handle_delete_command(message):
    """Ask user to confirm account deletion."""
    chat_id = message.chat.id
    users = load_users()
    if str(chat_id) not in users:
        bot.send_message(chat_id, "⚠️ אין לך חשבון פעיל בבוט.")
        return

    markup = types.InlineKeyboardMarkup()
    markup.row(
        types.InlineKeyboardButton("🗑️ כן, מחק אותי", callback_data="confirm_delete"),
        types.InlineKeyboardButton("❌ ביטול", callback_data="cancel_delete")
    )
    bot.send_message(
        chat_id,
        "⚠️ *האם אתה בטוח שברצונך למחוק את החשבון?*\n\n"
        "פעולה זו תמחק את כל הנתונים שלך (הגדרות, דירות שמורות) ולא ניתן לשחזרה.\n"
        "כדי להצטרף שוב תצטרך קוד הזמנה חדש.",
        parse_mode="Markdown",
        reply_markup=markup
    )


@bot.callback_query_handler(func=lambda call: call.data in ['confirm_delete', 'cancel_delete', 'confirm_delete_prompt'])
def handle_delete_callback(call):
    chat_id = call.message.chat.id

    if call.data == 'confirm_delete_prompt':
        markup = types.InlineKeyboardMarkup()
        markup.row(
            types.InlineKeyboardButton("🗑️ כן, מחק אותי", callback_data="confirm_delete"),
            types.InlineKeyboardButton("❌ ביטול", callback_data="cancel_delete")
        )
        bot.send_message(
            chat_id,
            "⚠️ *האם אתה בטוח שברצונך למחוק את החשבון?*\n\n"
            "פעולה זו תמחק את כל הנתונים שלך (הגדרות, דירות שמורות) ולא ניתן לשחזרה.\n"
            "כדי להצטרף שוב תצטרך קוד הזמנה חדש.",
            parse_mode="Markdown",
            reply_markup=markup
        )
        return

    try:
        bot.delete_message(chat_id, call.message.message_id)
    except Exception:
        pass

    if call.data == 'confirm_delete':
        remove_user(chat_id)
        user_data.pop(chat_id, None)
        logger.info(f"User {chat_id} deleted their account.")
        bot.send_message(
            chat_id,
            "✅ החשבון שלך נמחק בהצלחה.\n"
            "אם תרצה להצטרף שוב בעתיד, פנה למנהל לקבלת קוד הזמנה חדש."
        )
    else:
        bot.send_message(chat_id, "✅ הביטול בוצע. החשבון שלך נשאר פעיל.")


@bot.callback_query_handler(func=lambda call: call.data in ['start_setup', 'menu_edit'])
def handle_start_setup(call):
    chat_id = call.message.chat.id
    
    users = load_users()
    user_info = users.get(str(chat_id))
    if user_info:
        from urllib.parse import urlparse, parse_qs
        url = user_info.get('url', '')
        try:
            params = parse_qs(urlparse(url).query)
            if 'rooms' in params:
                rm = params['rooms'][0].split('-')
                if len(rm) == 2:
                    try:
                        user_data.setdefault(chat_id, {})['min_rooms'] = float(rm[0]) if rm[0] else 0
                        user_data.setdefault(chat_id, {})['max_rooms'] = float(rm[1]) if rm[1] else 99
                    except ValueError: pass
            if 'price' in params:
                pr = params['price'][0].split('-')
                if len(pr) == 2:
                    try:
                        user_data.setdefault(chat_id, {})['min_price'] = int(pr[0]) if pr[0] else 0
                        user_data.setdefault(chat_id, {})['max_price'] = int(pr[1]) if pr[1] else 9999999
                    except ValueError: pass
        except Exception: pass
        
    user_data.setdefault(chat_id, {})['setup_mode'] = True
    
    def get_status_str():
        p_min = user_data[chat_id].get('min_price', '?')
        p_max = user_data[chat_id].get('max_price', '?')
        r_min = user_data[chat_id].get('min_rooms', '?')
        r_max = user_data[chat_id].get('max_rooms', '?')
        
        p_min_str = "ללא הגבלה" if p_min == 0 else f"{p_min} ₪"
        p_max_str = "ללא הגבלה" if p_max == 9999999 else f"{p_max} ₪"
        r_min_str = "ללא הגבלה" if r_min == 0 else str(r_min)
        r_max_str = "ללא הגבלה" if r_max == 99 else str(r_max)
        return f"\u200F📌 **נבחר עד כה:**\n\u200F💰 מחיר: {p_min_str} - {p_max_str}\n\u200F🛏️ חדרים: {r_min_str} - {r_max_str}\n\n"

    prefix = get_status_str() if call.data == 'menu_edit' else "\u200Fבוא נגדיר את חיפוש הדירה המושלמת שלך ב-4 שלבים פשוטים.\n\n"
    text = f"{prefix}\u200F**שלב 1 מתוך 4: מה מחיר המינימום?**"
    try: bot.delete_message(chat_id, call.message.message_id)
    except: pass
    bot.send_message(chat_id, text, reply_markup=get_price_markup('min_price'), parse_mode="Markdown")


@bot.message_handler(commands=['menu', 'status'])
def send_menu(message):
    chat_id = message.chat.id
    user_data[chat_id] = {}
    send_dashboard(chat_id)

def send_dashboard(chat_id):
    users = load_users()
    user_info = users.get(str(chat_id))
    
    if not user_info:
        bot.send_message(chat_id, "\u200F⚠️ לא מצאתי הגדרות. שלח /start להתחלה.")
        return
        
    from urllib.parse import urlparse, parse_qs
    url = user_info.get('url', '')
    city = user_info.get('city', 'תל אביב')
    keywords = user_info.get('keywords', 'אין') or 'אין'
    neighborhoods = user_info.get('neighborhoods', 'כל השכונות') or 'כל השכונות'
    is_active = user_info.get('active', True)
    active_str = "▶️ מופעל" if is_active else "⏸️ מושהה"
    
    # Parse URL for rooms/price
    min_rooms, max_rooms = "?", "?"
    min_price, max_price = "?", "?"
    try:
        params = parse_qs(urlparse(url).query)
        if 'rooms' in params:
            rm = params['rooms'][0].split('-')
            min_rooms, max_rooms = rm[0], rm[1]
        if 'price' in params:
            pr = params['price'][0].split('-')
            min_price, max_price = pr[0], pr[1]
    except Exception:
        pass
        
    status_text = (
        f"\u200F📋 **לוח בקרה אישי:**\n\n"
        f"\u200Fסטטוס חיפוש: {active_str}\n"
        f"\u200F📍 עיר: {city}\n"
        f"\u200F🏙️ שכונות: {neighborhoods}\n"
        f"\u200F💰 טווח מחיר: {min_price} - {max_price} ₪\n"
        f"\u200F🛏️ טווח חדרים: {min_rooms} - {max_rooms}\n"
        f"\u200F🚫 מילים חסומות: {keywords}\n\n"
        f"\u200Fבחר פעולה מהתפריט למטה:"
    )
    bot.send_message(chat_id, status_text, parse_mode="Markdown", reply_markup=get_main_menu(is_active))


@bot.callback_query_handler(func=lambda call: call.data.startswith('menu_'))
def handle_menu_callbacks(call):
    chat_id = call.message.chat.id
    action = call.data.replace('menu_', '', 1)
    
    users = load_users()
    user_info = users.get(str(chat_id))
    
    if not user_info:
        bot.answer_callback_query(call.id, "\u200F⚠️ לא מצאתי הגדרות. שלח /start", show_alert=True)
        return

    if action == "edit":
        user_data[chat_id] = user_data.get(chat_id, {})
        user_data[chat_id]['setup_mode'] = False
        
        # Load prepopulated current values
        try:
            from urllib.parse import urlparse, parse_qs
            url = user_info.get('url', '')
            params = parse_qs(urlparse(url).query)
            if 'rooms' in params:
                rm = params['rooms'][0].split('-')
                user_data[chat_id]['min_rooms'] = float(rm[0])
                user_data[chat_id]['max_rooms'] = float(rm[1]) if rm[1] != '99' else 99
            if 'price' in params:
                pr = params['price'][0].split('-')
                user_data[chat_id]['min_price'] = int(pr[0])
                user_data[chat_id]['max_price'] = int(pr[1]) if pr[1] != '9999999' else 9999999
        except Exception:
            pass
            
        try: bot.delete_message(chat_id, call.message.message_id)
        except: pass
        bot.send_message(chat_id, "\u200Fבחר עיר לחיפוש (עריכת מסננים):", reply_markup=get_cities_markup())

    elif action == "toggle":
        is_active = user_info.get('active', True)
        set_user_active(chat_id, not is_active)
        new_state = "הושהה ⏸️" if is_active else "הופעל 🟢"
        bot.answer_callback_query(call.id, f"\u200Fהטיפול {new_state}", show_alert=False)
        try: bot.delete_message(chat_id, call.message.message_id)
        except: pass
        send_dashboard(chat_id)
        
    elif action == "back":
        try: bot.delete_message(chat_id, call.message.message_id)
        except: pass
        send_dashboard(chat_id)
        
    elif action.startswith("saved_"):
        try:
            page = int(action.replace("saved_", ""))
            saved_list = get_saved_apartments(str(chat_id))
            
            if not saved_list:
                text, markup = get_saved_apartments_display(saved_list, page)
            else:
                text, markup = get_saved_apartments_display(saved_list, page)
                
            try: bot.delete_message(chat_id, call.message.message_id)
            except: pass
            bot.send_message(chat_id, text, reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=True)
        except Exception as e:
            bot.send_message(chat_id, f"Error rendering page: {e}")

@bot.callback_query_handler(func=lambda call: call.data.startswith('save_ad_'))
def handle_save_ad(call):
    chat_id = call.message.chat.id
    # Format: save_ad_HASH_PRICE
    parts = call.data.split('_', 3)
    if len(parts) >= 3:
        ad_id = parts[2]
        # Try to parse price if available, otherwise "לא ידוע"
        price = parts[3] if len(parts) > 3 else "לא ידוע"
        
        # Build a title from the message text if possible
        msg_text = call.message.text or ""
        lines = msg_text.split('\n')
        title = lines[0] if lines else "דירה שמורה"
        
        # Get url from the first inline button if available
        url = ""
        if call.message.reply_markup and call.message.reply_markup.keyboard:
            for row in call.message.reply_markup.keyboard:
                for btn in row:
                    if btn.url:
                        url = btn.url
                        break
                if url: break
                
        if not url:
            url = f"https://www.yad2.co.il/item/{ad_id}" # Fallback
            
        try:
            save_apartment(str(chat_id), ad_id, title, price, url)
            bot.answer_callback_query(call.id, "✅ הדירה נשמרה בהצלחה בלוח הבקרה!", show_alert=True)
        except Exception as e:
            bot.answer_callback_query(call.id, f"❌ שגיאה בשמירת הדירה: {e}", show_alert=True)
    else:
        bot.answer_callback_query(call.id, "❌ המידע חסר בשמירת הדירה", show_alert=True)

@bot.callback_query_handler(func=lambda call: call.data.startswith('rm_ad_'))
def handle_rm_ad(call):
    chat_id = call.message.chat.id
    # Format: rm_ad_HASH_PAGE
    parts = call.data.split('_')
    if len(parts) >= 4:
        ad_id = parts[2]
        page = int(parts[3])
        remove_saved_apartment(str(chat_id), ad_id)
        bot.answer_callback_query(call.id, "🗑️ הדירה הוסרה מהמועדפים")
        
        # Refresh the view
        saved_list = get_saved_apartments(str(chat_id))
        if not saved_list:
            text = "\u200F⭐ *אין לך יותר דירות שמורות.*"
            try: bot.delete_message(chat_id, call.message.message_id)
            except: pass
            bot.send_message(chat_id, text, reply_markup=get_main_menu(), parse_mode="Markdown")
        else:
            # Rebalance page if we deleted the last item on the current page
            import math
            max_pages = max(0, math.ceil(len(saved_list) / 5) - 1)
            page = min(page, max_pages)
            
            text, markup = get_saved_apartments_display(saved_list, page)
            bot.edit_message_text(text, chat_id, call.message.message_id, reply_markup=markup, parse_mode="Markdown", disable_web_page_preview=True)

@bot.callback_query_handler(func=lambda call: call.data.startswith('kw_'))
def handle_keyword_callbacks(call):
    chat_id = call.message.chat.id
    action = call.data.replace('kw_', '')
    
    users = load_users()
    user_info = users.get(str(chat_id))
    if not user_info:
        return
        
    current_kws_str = user_info.get('keywords', '')
    kws = [k.strip() for k in current_kws_str.split(',') if k.strip()]
    
    if action == "menu":
        try: bot.delete_message(chat_id, call.message.message_id)
        except: pass
        bot.send_message(chat_id, "\u200F🚫 **ניהול מילים חסומות:**\n\u200F(דירות שיכילו מילים אלו **לא** ישלחו)", reply_markup=get_keywords_markup(current_kws_str), parse_mode="Markdown")
        
    elif action.startswith("rm_"):
        word = action.replace("rm_", "")
        kws = [k for k in kws if k != word]
        new_kws = ",".join(kws)
        update_user_keywords(chat_id, new_kws)
        try: bot.delete_message(chat_id, call.message.message_id)
        except: pass
        bot.send_message(chat_id, "\u200F🚫 **ניהול מילים חסומות:**\n\u200F(דירות שיכילו מילים אלו **לא** ישלחו)", reply_markup=get_keywords_markup(new_kws), parse_mode="Markdown")
        
    elif action.startswith("add_"):
        word = action.replace("add_", "")
        if word not in kws:
            kws.append(word)
        new_kws = ",".join(kws)
        update_user_keywords(chat_id, new_kws)
        try: bot.delete_message(chat_id, call.message.message_id)
        except: pass
        bot.send_message(chat_id, "\u200F🚫 **ניהול מילים חסומות:**\n\u200F(דירות שיכילו מילים אלו **לא** ישלחו)", reply_markup=get_keywords_markup(new_kws), parse_mode="Markdown")
        
    elif action == "custom":
        msg = bot.send_message(chat_id, "\u200Fהקלד מילה חסומה להוספה (או כמה מופרדות בפסיק):", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_add_custom_keyword)

def process_add_custom_keyword(message):
    chat_id = message.chat.id
    text = message.text.strip()
    
    users = load_users()
    user_info = users.get(str(chat_id))
    if user_info and text and text not in ["אין", "0", "כלום", "none", "None"]:
        current_kws_str = user_info.get('keywords', '')
        kws = [k.strip() for k in current_kws_str.split(',') if k.strip()]
        new_words = [w.strip() for w in text.split(',')]
        for bw in new_words:
            if bw and bw not in kws:
                kws.append(bw)
        new_kws = ",".join(kws)
        update_user_keywords(chat_id, new_kws)
        
    bot.send_message(chat_id, "\u200F✅ רשימת המילים התעדכנה.", parse_mode="Markdown")
    send_dashboard(chat_id)

@bot.callback_query_handler(func=lambda call: call.data.startswith('nb_'))
def handle_neighborhood_callbacks(call):
    chat_id = call.message.chat.id
    action = call.data.replace('nb_', '')
    
    users = load_users()
    user_info = users.get(str(chat_id))
    if not user_info:
        return
        
    current_nbs_str = user_info.get('neighborhoods', '')
    nbs = [k.strip() for k in current_nbs_str.split(',') if k.strip()]
    
    if action == "menu":
        try: bot.delete_message(chat_id, call.message.message_id)
        except: pass
        text = (
            "\u200F🏙️ **בחירת שכונות למעקב:**\n"
            "\u200F*(אם לא תבחר אף שכונה, תקבל דירות מכל העיר)*\n\n"
            "\u200F✔️ - שכונות שנבחרו (לחץ להסרה)\n"
            "\u200F➕ - הוספת שכונה מהרשימה"
        )
        bot.send_message(chat_id, text, reply_markup=get_neighborhoods_markup(current_nbs_str), parse_mode="Markdown")
        
    elif action.startswith("rm_"):
        word = action.replace("rm_", "")
        nbs = [k for k in nbs if k != word]
        new_nbs = ",".join(nbs)
        update_user_neighborhoods(chat_id, new_nbs)
        try: bot.delete_message(chat_id, call.message.message_id)
        except: pass
        text = (
            "\u200F🏙️ **בחירת שכונות למעקב:**\n"
            "\u200F*(אם לא תבחר אף שכונה, תקבל דירות מכל העיר)*\n\n"
            "\u200F✔️ - שכונות שנבחרו (לחץ להסרה)\n"
            "\u200F➕ - הוספת שכונה מהרשימה"
        )
        bot.send_message(chat_id, text, reply_markup=get_neighborhoods_markup(new_nbs), parse_mode="Markdown")
        
    elif action.startswith("add_"):
        word = action.replace("add_", "")
        if word not in nbs:
            nbs.append(word)
        new_nbs = ",".join(nbs)
        update_user_neighborhoods(chat_id, new_nbs)
        try: bot.delete_message(chat_id, call.message.message_id)
        except: pass
        text = (
            "\u200F🏙️ **בחירת שכונות למעקב:**\n"
            "\u200F*(אם לא תבחר אף שכונה, תקבל דירות מכל העיר)*\n\n"
            "\u200F✔️ - שכונות שנבחרו (לחץ להסרה)\n"
            "\u200F➕ - הוספת שכונה מהרשימה"
        )
        bot.send_message(chat_id, text, reply_markup=get_neighborhoods_markup(new_nbs), parse_mode="Markdown")
        
    elif action == "custom":
        msg = bot.send_message(chat_id, "\u200Fהקלד שם או חלקיות שם של שכונה להוספה (או כמה מופרדות בפסיק):", parse_mode="Markdown")
        bot.register_next_step_handler(msg, process_add_custom_neighborhood)

def process_add_custom_neighborhood(message):
    chat_id = message.chat.id
    text = message.text.strip()
    
    users = load_users()
    user_info = users.get(str(chat_id))
    if user_info and text and text not in ["אין", "0", "כלום", "none", "None"]:
        current_nbs_str = user_info.get('neighborhoods', '')
        nbs = [k.strip() for k in current_nbs_str.split(',') if k.strip()]
        new_words = [w.strip() for w in text.split(',')]
        for bw in new_words:
            if bw and bw not in nbs:
                nbs.append(bw)
        new_nbs = ",".join(nbs)
        update_user_neighborhoods(chat_id, new_nbs)
        
    bot.send_message(chat_id, "\u200F✅ רשימת השכונות התעדכנה.", parse_mode="Markdown")
    send_dashboard(chat_id)

# -------- SETUP WIZARD --------
@bot.callback_query_handler(func=lambda call: call.data.startswith('setup_'))
def handle_setup_callbacks(call):
    chat_id = call.message.chat.id
    data = call.data.replace('setup_', '')
    
    user_data[chat_id] = user_data.get(chat_id, {})
    is_setup = user_data[chat_id].get('setup_mode', False)
    
    def get_status_str():
        if not is_setup: return ""
        p_min = user_data[chat_id].get('min_price', '?')
        p_max = user_data[chat_id].get('max_price', '?')
        r_min = user_data[chat_id].get('min_rooms', '?')
        r_max = user_data[chat_id].get('max_rooms', '?')
        
        # Format "ללא הגבלה" correctly
        p_min_str = "ללא הגבלה" if p_min == 0 else f"{p_min} ₪"
        p_max_str = "ללא הגבלה" if p_max == 9999999 else f"{p_max} ₪"
        r_min_str = "ללא הגבלה" if r_min == 0 else str(r_min)
        r_max_str = "ללא הגבלה" if r_max == 99 else str(r_max)
        
        return f"\u200F📌 **נבחר עד כה:**\n\u200F💰 מחיר: {p_min_str} - {p_max_str}\n\u200F🛏️ חדרים: {r_min_str} - {r_max_str}\n\n"
    
    if data.startswith('min_price_'):
        val = int(data.replace('min_price_', ''))
        user_data[chat_id]['min_price'] = val
        try: bot.delete_message(chat_id, call.message.message_id)
        except: pass
        if is_setup:
            bot.send_message(chat_id, f"{get_status_str()}\u200F**שלב 2 מתוך 4: מה מחיר המקסימום?**", reply_markup=get_price_markup('max_price'), parse_mode="Markdown")
        else:
            p_min_str = "ללא הגבלה" if val == 0 else f"{val} ₪"
            bot.send_message(chat_id, f"\u200F💰 מינימום: {p_min_str}\n\n\u200Fבחר מחיר מקסימום חדש:", reply_markup=get_price_markup('max_price'), parse_mode="Markdown")

    elif data.startswith('max_price_'):
        val = int(data.replace('max_price_', ''))
        min_p = user_data[chat_id].get('min_price', 0)
        # Swap logic ONLY if neither limit is set to "No Limit"
        if val < min_p and val != 9999999 and min_p != 0:
            val, min_p = min_p, val
            user_data[chat_id]['min_price'] = min_p
        user_data[chat_id]['max_price'] = val
        
        try: bot.delete_message(chat_id, call.message.message_id)
        except: pass
        if is_setup:
            bot.send_message(chat_id, f"{get_status_str()}\u200F**שלב 3 מתוך 4: שווי מינימום חדרים?**", reply_markup=get_rooms_markup('min_rooms'), parse_mode="Markdown")
        else:
            _rebuild_user_url(chat_id)
            p_min_str = "ללא הגבלה" if min_p == 0 else f"{min_p} ₪"
            p_max_str = "ללא הגבלה" if val == 9999999 else f"{val} ₪"
            bot.send_message(chat_id, f"\u200F✅ טווח מחירים עודכן ל: {p_min_str} - {p_max_str}", parse_mode="Markdown")
            send_dashboard(chat_id)

    elif data.startswith('min_rooms_'):
        val = float(data.replace('min_rooms_', ''))
        user_data[chat_id]['min_rooms'] = val
        
        try: bot.delete_message(chat_id, call.message.message_id)
        except: pass
        if is_setup:
            bot.send_message(chat_id, f"{get_status_str()}\u200F**שלב 4 מתוך 4: שווי מקסימום חדרים?**", reply_markup=get_rooms_markup('max_rooms'), parse_mode="Markdown")
        else:
            r_min_str = "ללא הגבלה" if val == 0 else str(val)
            bot.send_message(chat_id, f"\u200F🛏️ מינימום חדרים: {r_min_str}\n\n\u200Fבחר מקסימום חדרים חדש:", reply_markup=get_rooms_markup('max_rooms'), parse_mode="Markdown")

    elif data.startswith('max_rooms_'):
        val = float(data.replace('max_rooms_', ''))
        min_r = user_data[chat_id].get('min_rooms', 0)
        # Swap logic ONLY if neither limit is set to "No Limit"
        if val < min_r and val != 99 and min_r != 0:
            val, min_r = min_r, val
            user_data[chat_id]['min_rooms'] = min_r
        user_data[chat_id]['max_rooms'] = val
        
        try: bot.delete_message(chat_id, call.message.message_id)
        except: pass
        
        if is_setup:
            # We are done!
            user_data[chat_id]['setup_mode'] = False
            _rebuild_user_url(chat_id)
            
            bot.send_message(
                chat_id,
                f"\u200F🎉 **ההגדרות הושלמו בהצלחה! הבוט יתחיל לחפש עבורך!**\n\n"
                f"{get_status_str()}"
                f"\u200Fתוכל לערוך מילים חסומות או פילטרים אחרים דרך התפריט.", 
                parse_mode="Markdown", 
                reply_markup=get_main_menu()
            )
        else:
            _rebuild_user_url(chat_id)
            r_min_str = "ללא הגבלה" if min_r == 0 else str(min_r)
            r_max_str = "ללא הגבלה" if val == 99 else str(val)
            bot.send_message(chat_id, f"\u200F✅ טווח חדרים עודכן ל: {r_min_str} - {r_max_str}", parse_mode="Markdown")
            send_dashboard(chat_id)


# -------- TEXT EDIT PROCESSORS (For targeted edits if they still want text) --------
def process_price_update(message):
    chat_id = message.chat.id
    try:
        parts = message.text.split('-')
        min_p = int(parts[0].strip())
        max_p = int(parts[1].strip())
        if min_p > max_p:
            min_p, max_p = max_p, min_p
            
        user_data[chat_id] = user_data.get(chat_id, {})
        user_data[chat_id]['min_price'] = min_p
        user_data[chat_id]['max_price'] = max_p
        _rebuild_user_url(chat_id)
        
        bot.send_message(chat_id, f"\u200F✅ טווח מחירים עודכן חופשית: {min_p}-{max_p} ₪", parse_mode="Markdown")
        send_dashboard(chat_id)
    except:
        msg = bot.send_message(chat_id, "\u200F⚠️ פורמט לא תקין. נסה שוב (לדוגמה: 4000-6000), או שלח /menu לביטול.")
        bot.register_next_step_handler(msg, process_price_update)

def process_rooms_update(message):
    chat_id = message.chat.id
    try:
        parts = message.text.split('-')
        min_r = float(parts[0].strip())
        max_r = float(parts[1].strip())
        if min_r > max_r:
            min_r, max_r = max_r, min_r
            
        user_data[chat_id] = user_data.get(chat_id, {})
        user_data[chat_id]['min_rooms'] = min_r
        user_data[chat_id]['max_rooms'] = max_r
        _rebuild_user_url(chat_id)
        
        bot.send_message(chat_id, f"\u200F✅ טווח חדרים עודכן חופשית: {min_r}-{max_r}", parse_mode="Markdown")
        send_dashboard(chat_id)
    except:
        msg = bot.send_message(chat_id, "\u200F⚠️ פורמט לא תקין. נסה שוב (לדוגמה: 2.5-3.5), או שלח /menu לביטול.")
        bot.register_next_step_handler(msg, process_rooms_update)

def process_keywords_update(message):
    chat_id = message.chat.id
    text = message.text.strip()
    if text in ["אין", "0", "כלום", "none", "None"]:
        text = ""
    update_user_keywords(chat_id, text)
    bot.send_message(chat_id, f"\u200F✅ מילים חסומות עודכנו: {text if text else 'אין'}", reply_markup=get_main_menu())

def _rebuild_user_url(chat_id):
    """Reconstructs the Yad2 URL based on current DB city and current memory/db params."""
    users = load_users()
    user_info = users.get(str(chat_id))
    if not user_info:
        return
        
    city = user_info.get('city', 'תל אביב')
    old_url = user_info.get('url', '')
    
    # Try to extract existing params from old url to preserve them if not actively editing them
    from urllib.parse import urlparse, parse_qs
    min_rooms, max_rooms = 1.5, 3
    min_price, max_price = 5000, 6700
    try:
        params = parse_qs(urlparse(old_url).query)
        if 'rooms' in params:
            rm = params['rooms'][0].split('-')
            if len(rm) == 2:
                try: 
                    min_rooms = float(rm[0]) if rm[0] else 0
                    max_rooms = float(rm[1]) if rm[1] else 99
                except ValueError: pass
        if 'price' in params:
            pr = params['price'][0].split('-')
            if len(pr) == 2:
                try: 
                    min_price = int(pr[0]) if pr[0] else 0
                    max_price = int(pr[1]) if pr[1] else 9999999
                except ValueError: pass
    except Exception as e:
        logger.error(f"Error parsing old url: {e}")

    # Override with memory if recently edited
    if chat_id in user_data:
        min_rooms = user_data[chat_id].get('min_rooms', min_rooms)
        max_rooms = user_data[chat_id].get('max_rooms', max_rooms)
        min_price = user_data[chat_id].get('min_price', min_price)
        max_price = user_data[chat_id].get('max_price', max_price)

    config = {
        'city': city,
        'min_rooms': min_rooms,
        'max_rooms': max_rooms,
        'min_price': min_price,
        'max_price': max_price
    }
    new_url = construct_url(config)
    update_user_url(chat_id, new_url)


@bot.callback_query_handler(func=lambda call: call.data == 'delete_ad')
def handle_delete_ad(call):
    try:
        bot.delete_message(call.message.chat.id, call.message.message_id)
    except Exception as e:
        logger.error(f"Failed to delete message: {e}")

# Legacy fallback handlers to quietly handle text commands from the old keyboard markup
@bot.message_handler(func=lambda message: message.text in ["✅ הפעל התראות", "🛑 עצור התראות", "🔍 מסנן חדש", "🚀 התחל חיפוש"])
def handle_legacy_keyboards(message):
    bot.reply_to(message, "\u200Fשדרגנו את הממשק! השתמש בכפתורים שבהודעה החדשה או שלח /menu", reply_markup=types.ReplyKeyboardRemove())
    show_menu(message)

def run_bot():
    logger.info("Bot started...")
    bot.infinity_polling()
