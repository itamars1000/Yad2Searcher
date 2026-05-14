import time
import random
import requests
import html
from datetime import datetime
from urllib.parse import urlparse, parse_qs
from telebot import types

from config import bot, APIFY_TOKEN, APIFY_ACTOR_URL, FACEBOOK_GROUPS, FB_MIN_SLEEP, FB_MAX_SLEEP, logger
from database import load_users, is_ad_notified, mark_ad_notified
from utils import parse_facebook_posts_batch, generate_post_hash, send_apartment_alert, contains_blocked_keywords, satisfies_neighborhood_filter

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
        "resultsLimit": 3,
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

    # Pass 1: collect posts that have text
    valid_posts = []
    for post in posts:
        post_text = post.get("text", "")
        if not post_text:
            logger.warning(f"Skipping post with missing text. Keys present: {list(post.keys())}")
            no_id_count += 1
            continue
        post_id = str(post.get("postId") or post.get("id") or generate_post_hash(post_text))
        post_url = post.get("url") or post.get("facebookUrl", "")
        valid_posts.append((post, post_id, post_url, post_text))

    # Single Gemini call for all valid posts
    batch_results = parse_facebook_posts_batch([p[3] for p in valid_posts]) if valid_posts else []

    # Pass 2: process each post with its parsed result
    for (post, post_id, post_url, post_text), parsed_data in zip(valid_posts, batch_results):
        post_rooms = parsed_data["rooms"]
        post_price = parsed_data["price"]

        if post_rooms is None or post_price is None:
            if not parsed_data.get("not_for_rent"):
                # Only warn if this looks like a rental post we genuinely failed to parse
                skip_words = ("סאבלט", "מחפש", "מחפשת", "מחפשים")
                apartment_keywords = ("חדרים", "שכירות", "דירה", "להשכרה")
                if any(kw in post_text for kw in apartment_keywords) and not any(w in post_text for w in skip_words):
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

            safe_text = html.escape(post_text)

            price_val = parsed_data.get("price")
            rooms_val = parsed_data.get("rooms")
            price_text = f"{price_val:,} ₪" if price_val else "לא ידוע"
            rooms_text = str(rooms_val) if rooms_val is not None else "לא ידוע"

            msg = (
                f"\u200F👤 <b>פוסט חדש בפייסבוק!</b>\n\n"
                f"\u200F💰 <b>מחיר:</b> {price_text}\n"
                f"\u200F🛏️ <b>חדרים:</b> {rooms_text}\n\n"
                f"\u200F{safe_text}\n\n"
                f"\u200F🔗 <a href='{post_url}'>למקור הפוסט בפייסבוק</a>"
            )

            try:
                price_str = str(price_val) if price_val else "0"
                price_numeric = ''.join(filter(str.isdigit, price_str))
                if not price_numeric:
                    price_numeric = "0"
                    
                # Use a shorter ID for the button to avoid Telegram's 64-byte callback_data limit
                short_id = content_hash.replace("fb_", "")[:16]
                
                # Format inline keyboard
                markup = types.InlineKeyboardMarkup()
                btn_save = types.InlineKeyboardButton("⭐ שמור דירה", callback_data=f"save_ad_{short_id}_{price_numeric}")
                markup.row(btn_save)

                # Extract images
                images = []
                
                # Check for attachments (Apify Facebook Groups Scraper format)
                for att in post.get("attachments", []):
                    if not isinstance(att, dict):
                        continue
                    url = None
                    if "image" in att and isinstance(att["image"], dict):
                        url = att["image"].get("uri")
                    elif "photo_image" in att and isinstance(att["photo_image"], dict):
                        url = att["photo_image"].get("uri")
                    else:
                        url = att.get("thumbnail")
                        
                    # Verify it's not a generic media set link
                    if url and isinstance(url, str) and url.startswith("http") and "facebook.com/media/set" not in url:
                        images.append(url)

                # Fallback for list of image URLs (common in some parsers)
                if not images:
                    for img in post.get("images", []):
                        if isinstance(img, str) and img.startswith("http"):
                            images.append(img)
                        elif isinstance(img, dict):
                            url = img.get("url") or img.get("image")
                            if url and url.startswith("http"):
                                images.append(url)
                            
                if not images:
                    for m in post.get("media", []):
                        if isinstance(m, dict):
                            url = m.get("image") or m.get("thumbnail") or m.get("url")
                            if url and url.startswith("http"):
                                images.append(url)

                # 1. Send the main text message FIRST (so images appear underneath it)
                bot.send_message(user_id, msg, parse_mode="HTML", disable_web_page_preview=True)
                
                # 2. Send images if any
                if images:
                    from telebot.types import InputMediaPhoto
                    import requests
                    
                    media_group = []
                    for img_url in images[:10]:
                        try:
                            # Download image to memory to bypass Telegram CDN block (WEBPAGE_CURL_FAILED)
                            r = requests.get(img_url, timeout=5)
                            if r.status_code == 200:
                                media_group.append(InputMediaPhoto(r.content))
                        except Exception as dl_err:
                            logger.warning(f"Failed to download image bypass: {dl_err}")
                            continue

                    if media_group:
                        try:
                            bot.send_media_group(user_id, media_group)
                        except Exception as media_err:
                            logger.warning(f"Failed to send media group for {post_id}: {media_err}")
                
                # 3. Send the save button separately
                bot.send_message(user_id, "אהבתם את הדירה? תוכלו לשמור אותה במועדפים 👇", reply_markup=markup)
                
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
        sleep_time = random.randint(FB_MIN_SLEEP, FB_MAX_SLEEP)
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
