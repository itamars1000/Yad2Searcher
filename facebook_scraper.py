import time
import random
import requests
import html
from datetime import datetime
from urllib.parse import urlparse, parse_qs
from telebot import types

from config import bot, APIFY_TOKEN, APIFY_ACTOR_URL, FACEBOOK_GROUPS, MIN_SLEEP, MAX_SLEEP, logger
from database import load_users, is_ad_notified, mark_ad_notified
from utils import parse_facebook_post, generate_post_hash, send_apartment_alert, contains_blocked_keywords, satisfies_neighborhood_filter

APIFY_BASE_URL = "https://api.apify.com/v2"


def _parse_user_limits(url):
    """Extracts min/max rooms and price from a stored Yad2 search URL."""
    try:
        params = parse_qs(urlparse(url).query)
        
        # Helper to parse range strings like "3-5", "4-", or "-10"
        def parse_range(param_name, default_min, default_max, is_float=False):
            val = params.get(param_name, [f"{default_min}-{default_max}"])[0]
            parts = val.split("-")
            
            # Ensure we have at least 2 parts even if input is "3" or ""
            while len(parts) < 2:
                parts.append("")
                
            p_min = parts[0].strip()
            p_max = parts[1].strip()
            
            conv = float if is_float else int
            
            res_min = conv(p_min) if p_min else conv(default_min)
            res_max = conv(p_max) if p_max else conv(default_max)
            return res_min, res_max

        min_rooms, max_rooms = parse_range("rooms", 0, 99, is_float=True)
        min_price, max_price = parse_range("price", 0, 9999999)

        return {
            "min_rooms": min_rooms,
            "max_rooms": max_rooms,
            "min_price": min_price,
            "max_price": max_price,
        }
    except Exception as e:
        logger.error(f"Error parsing user URL limits: {e}")
        return None


def _fetch_posts():
    """Triggers an Apify actor run and returns the dataset items once complete."""
    headers = {"Authorization": f"Bearer {APIFY_TOKEN}"}
    payload = {
        "startUrls": [{"url": url} for url in FACEBOOK_GROUPS],
        "resultsLimit": 5,
    }

    # Start the run
    logger.info("Starting Apify actor run...")
    response = requests.post(f"{APIFY_ACTOR_URL}?memory=256", json=payload, headers=headers, timeout=30)
    response.raise_for_status()
    run_data = response.json().get("data", {})
    run_id = run_data.get("id")
    dataset_id = run_data.get("defaultDatasetId")

    if not run_id:
        logger.error("No run ID returned from Apify.")
        return []

    logger.info(f"Apify run started: {run_id}")

    # Poll for completion (up to 20 attempts x 10s = 200 seconds)
    status_url = f"{APIFY_BASE_URL}/actor-runs/{run_id}"
    for attempt in range(20):
        time.sleep(10)
        status_resp = requests.get(status_url, headers=headers, timeout=15)
        status_resp.raise_for_status()
        status = status_resp.json().get("data", {}).get("status")
        logger.info(f"Apify run {run_id} status: {status} (attempt {attempt + 1}/20)")
        if status == "SUCCEEDED":
            break
        if status in ("FAILED", "ABORTED", "TIMED-OUT"):
            logger.error(f"Apify run ended with status: {status}")
            return []
    else:
        logger.error("Apify run timed out waiting for completion.")
        return []

    # Fetch dataset items
    items_url = f"{APIFY_BASE_URL}/datasets/{dataset_id}/items"
    items_resp = requests.get(items_url, headers=headers, timeout=30)
    items_resp.raise_for_status()
    return items_resp.json()


def _scrape_cycle():
    logger.info("--- Starting Facebook Scraper Cycle ---")

    try:
        posts = _fetch_posts()
    except Exception as e:
        logger.error(f"Failed to fetch posts from Apify: {e}")
        return

    if not posts:
        logger.info("No posts returned from Apify.")
        return

    users = load_users()
    active_users = {uid: data for uid, data in users.items() if data.get("active")}

    logger.info(f"[Smart Batch FB] 1 Apify call → {len(posts)} posts → fan-out to {len(active_users)} active user(s).")

    if not active_users:
        logger.info("No active users.")
        return


    no_id_count = 0
    no_parse_count = 0
    already_notified_count = 0
    no_match_count = 0
    blocked_keyword_count = 0
    blocked_neighborhood_count = 0
    sent_count = 0
    error_count = 0

    for post in posts:
        post_id = str(post.get("postId") or post.get("id") or "")
        post_text = post.get("text", "")
        post_url = post.get("url", "")

        if not post_id or not post_text:
            logger.debug("Skipping post with missing id or text.")
            no_id_count += 1
            continue

        parsed_data = parse_facebook_post(post_text)
        if not parsed_data:
            logger.debug(f"Post {post_id}: could not extract price/rooms. Skipping.")
            if "חדרים" in post_text or "שכירות" in post_text or "דירה" in post_text:
                logger.warning(f"MISSED APARTMENT? Raw text: {post_text}")
            no_parse_count += 1
            continue

        post_rooms = parsed_data["rooms"]
        post_price = parsed_data["price"]

        if post_rooms is None or post_price is None:
            logger.debug(f"Post {post_id}: missing rooms or price after parsing. Skipping.")
            if "חדרים" in post_text or "שכירות" in post_text or "דירה" in post_text:
                logger.debug(f"DEBUG PARSE RESULT: {parsed_data}")
                logger.warning(f"MISSED APARTMENT? Raw text: {post_text}")
            no_parse_count += 1
            continue

        for user_id, user_data in active_users.items():
            # Skip users who haven't completed setup (no URL at all)
            user_url = user_data.get("url", "")
            if not user_url:
                logger.debug(f"FB: User {user_id} skipped (no URL set).")
                continue

            limits = _parse_user_limits(user_data.get("url", ""))
            if not limits:
                continue

            if not (limits["min_rooms"] <= post_rooms <= limits["max_rooms"]):
                no_match_count += 1
                continue

            if not (limits["min_price"] <= post_price <= limits["max_price"]):
                no_match_count += 1
                continue
                
            keywords_str = user_data.get("keywords", "")
            neighborhoods_str = user_data.get("neighborhoods", "")
            if contains_blocked_keywords(post_text, keywords_str):
                logger.debug(f"Post {post_id} blocked due to keyword filter for user {user_id}")
                blocked_keyword_count += 1
                continue
                
            if not satisfies_neighborhood_filter(post_text, neighborhoods_str):
                logger.debug(f"Post {post_id} blocked due to neighborhood filter for user {user_id}")
                blocked_neighborhood_count += 1
                continue

            content_hash = f"fb_{generate_post_hash(post_text)}"
            if is_ad_notified(content_hash, user_id):
                logger.debug(f"Post {post_id} (hash {content_hash}) already notified to user {user_id}. Skipping.")
                already_notified_count += 1
                continue

            # The original message string is not used directly with send_apartment_alert,
            # but the parsed_data is.
            # The instruction implies the message content is still relevant for context,
            # but the actual sending mechanism changes.
            # Keeping the msg variable for clarity if needed elsewhere, though it's not used in the new send_apartment_alert call.
            # Escape HTML special characters to prevent "can't parse entities" errors
            safe_text = html.escape(post_text)
            msg = (
                f"\u200F👤 <b>פוסט חדש בפייסבוק!</b>\n"
                f"\u200F{safe_text}\n"
            )

            try:
                price_str = str(parsed_data.get("price", "לא ידוע"))
                price_numeric = ''.join(filter(str.isdigit, price_str))
                if not price_numeric:
                    price_numeric = "0"
                    
                # Use a shorter ID for the button to avoid Telegram's 64-byte callback_data limit
                short_id = content_hash.replace("fb_", "")[:16]
                
                # Format inline keyboard
                markup = types.InlineKeyboardMarkup()
                btn_link = types.InlineKeyboardButton("🔗 לצפייה בפוסט", url=post_url)
                btn_save = types.InlineKeyboardButton("⭐ שמור דירה", callback_data=f"save_ad_{short_id}_{price_numeric}")
                markup.row(btn_link)
                markup.row(btn_save)

                bot.send_message(user_id, msg, parse_mode="HTML", reply_markup=markup, disable_web_page_preview=True)
                mark_ad_notified(content_hash, user_id)
                logger.info(f"Facebook Post {post_id} sent to user {user_id}.")
                sent_count += 1
                
            except Exception as e:
                logger.error(f"Failed to send post {post_id} to user {user_id}: {e}")
                error_count += 1


    logger.info(
        f"📊 Facebook Scan Summary: "
        f"Fetched {len(posts)} | "
        f"No id/text {no_id_count} | "
        f"Unparseable {no_parse_count} | "
        f"No filter match {no_match_count} | "
        f"Blocked via kW {blocked_keyword_count} | "
        f"Blocked via nB {blocked_neighborhood_count} | "
        f"Already notified {already_notified_count} | "
        f"Errors {error_count} | "
        f"NEW sent {sent_count}"
    )

def run_facebook_scraper():
    # Run immediately on startup
    try:
        _scrape_cycle()
    except Exception as e:
        logger.critical(f"Critical Facebook Scraper Error: {e}")

    while True:
        sleep_time = random.randint(MIN_SLEEP, MAX_SLEEP)
        logger.info(f"Facebook scraper sleeping for {sleep_time // 60} minutes ({sleep_time}s)...")
        time.sleep(sleep_time)

        hour = datetime.now().hour
        if 0 <= hour < 7:
            logger.info("Night mode active. Skipping Facebook scan for an hour.")
            time.sleep(3600)
            continue

        try:
            _scrape_cycle()
        except Exception as e:
            logger.critical(f"Critical Facebook Scraper Error: {e}")
