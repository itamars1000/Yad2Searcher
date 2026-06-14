import re
import os
import time
import random
from datetime import datetime
from urllib.parse import urlparse, parse_qs
from telebot import types

# Prefer patchright (a patched, stealthier drop-in for Playwright) when installed;
# fall back to vanilla Playwright + playwright-stealth so nothing breaks if it's absent.
try:
    from patchright.sync_api import sync_playwright
    _USING_PATCHRIGHT = True
except ImportError:
    from playwright.sync_api import sync_playwright
    _USING_PATCHRIGHT = False

try:
    from playwright_stealth import Stealth
except ImportError:
    Stealth = None

from config import bot, MIN_SLEEP, MAX_SLEEP, MASTER_SCRAPE_URL, logger
from database import load_users, is_ad_notified, mark_if_new
from utils import parse_hebrew_date, contains_blocked_keywords, satisfies_neighborhood_filter

# Reuse one browser profile across cycles so the PerimeterX cookie (_px3) persists and
# we don't face a fresh challenge on every single scrape.
USER_DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".pw_profile")
# Headless Chromium is easy to fingerprint. Set HEADFUL=1 only with a real display
# (xvfb-run was unreliable in the base image — see Dockerfile); default is headless.
HEADFUL = os.getenv("HEADFUL", "0") == "1"
# Optional: use real Chrome ("chrome") instead of bundled Chromium for a stronger
# fingerprint. Requires Chrome installed in the image; unset = bundled Chromium.
BROWSER_CHANNEL = os.getenv("BROWSER_CHANNEL", "").strip()
# Residential proxy — the durable fix for Yad2's datacenter-IP block. Leave
# PROXY_SERVER empty to scrape directly. Format: PROXY_SERVER="http://host:port"
# (or socks5://...), with credentials in PROXY_USERNAME / PROXY_PASSWORD.
PROXY_SERVER = os.getenv("PROXY_SERVER", "").strip()
PROXY_USERNAME = os.getenv("PROXY_USERNAME", "").strip()
PROXY_PASSWORD = os.getenv("PROXY_PASSWORD", "").strip()

# --- Helpers ---
def extract_ad_id(link):
    try:
        path = urlparse(link).path
        if "/item/" in path:
            return path.split("/item/")[-1]
        return None
    except:
        return None

def _parse_user_price_rooms(url):
    """Extract min/max price and rooms from a user's stored search URL."""
    try:
        params = parse_qs(urlparse(url).query)
        min_price, max_price = 0, 99999999
        min_rooms, max_rooms = 0.0, 99.0

        if 'price' in params:
            pr = params['price'][0].split('-')
            min_price = int(pr[0]) if pr[0].isdigit() else 0
            max_price = int(pr[1]) if len(pr) > 1 and pr[1].isdigit() else 99999999

        if 'rooms' in params:
            rm = params['rooms'][0].split('-')
            try: min_rooms = float(rm[0])
            except: pass
            try: max_rooms = float(rm[1]) if len(rm) > 1 else 99.0
            except: pass

        return min_price, max_price, min_rooms, max_rooms
    except Exception as e:
        logger.warning(f"Could not parse user URL filters: {e}")
        return 0, 99999999, 0.0, 99.0

def _ad_matches_user(ad, user_id, user_data):
    """
    Check if a scraped ad should be sent to a specific user.
    Applies: price range, rooms range, keywords, neighborhoods, dedup.
    Returns True if the ad should be sent.
    """
    # Skip paused users
    if not user_data.get('active', True):
        return False

    # Deduplication
    if is_ad_notified(ad['ad_id'], user_id):
        return False

    # Price range check
    min_price, max_price, min_rooms, max_rooms = _parse_user_price_rooms(user_data.get('url', ''))
    price_num = ad.get('price_numeric', 0)
    if price_num > 0 and not (min_price <= price_num <= max_price):
        return False

    # Rooms range check
    rooms_num = ad.get('rooms_numeric', -1)
    if rooms_num >= 0 and not (min_rooms <= rooms_num <= max_rooms):
        return False

    # Keyword blocker
    keywords_str = user_data.get('keywords', '')
    if contains_blocked_keywords(ad.get('feed_text', ''), keywords_str):
        return False

    # Neighborhood whitelist
    neighborhoods_str = user_data.get('neighborhoods', '')
    if not satisfies_neighborhood_filter(ad.get('feed_text', ''), neighborhoods_str):
        return False

    return True


def _launch_context(p):
    """Launch a persistent browser context — cookies/profile survive between cycles."""
    kwargs = {
        "headless": not HEADFUL,
        # No hardcoded user_agent: let the real browser UA show so it can't mismatch
        # the navigator fingerprint (a classic bot tell).
        "viewport": {"width": random.randint(1800, 1920), "height": random.randint(900, 1080)},
        "locale": "he-IL",
    }
    if BROWSER_CHANNEL:
        kwargs["channel"] = BROWSER_CHANNEL
    if PROXY_SERVER:
        proxy = {"server": PROXY_SERVER}
        if PROXY_USERNAME:
            proxy["username"] = PROXY_USERNAME
            proxy["password"] = PROXY_PASSWORD
        kwargs["proxy"] = proxy
        logger.info(f"[Yad2] Routing through proxy {PROXY_SERVER}")
    return p.chromium.launch_persistent_context(USER_DATA_DIR, **kwargs)


def _handle_press_and_hold(page):
    """
    Best-effort PerimeterX 'press & hold' solver. PX renders the challenge in a
    container (commonly #px-captcha); we hold the mouse over it for several seconds.
    Heuristic and harmless when no challenge is present — PX changes often, so this
    won't always work, but it's free to try.
    """
    try:
        captcha = page.locator("#px-captcha")
        if captcha.count() == 0:
            return False
        box = captcha.bounding_box()
        if not box:
            return False
        cx = box["x"] + box["width"] / 2
        cy = box["y"] + box["height"] / 2
        logger.warning("[Yad2] PerimeterX challenge detected — attempting press & hold.")
        page.mouse.move(cx, cy)
        page.mouse.down()
        time.sleep(random.uniform(6, 9))
        page.mouse.up()
        try:
            page.wait_for_selector("li[data-nagish='feed-item-list-box']", timeout=15000)
        except Exception:
            pass
        return True
    except Exception as e:
        logger.warning(f"[Yad2] press-and-hold attempt failed: {e}")
        return False


def _scrape_all_items(context):
    """
    Opens the MASTER_SCRAPE_URL once and returns a list of ad dicts.
    All heavy DOM extraction happens here.
    """
    page = context.new_page()
    # Only stack playwright-stealth on the vanilla path; patchright already patches at
    # a lower level and layering stealth on top of it can break it.
    if not _USING_PATCHRIGHT and Stealth is not None:
        Stealth().apply_stealth_sync(page)

    ads = []
    try:
        # Retry logic
        for attempt in range(3):
            try:
                page.goto(MASTER_SCRAPE_URL, timeout=30000)
                break
            except Exception as e:
                if attempt < 2:
                    logger.warning(f"Page load attempt {attempt+1} failed: {e}. Retrying in 10s...")
                    time.sleep(10)
                else:
                    raise

        # If PerimeterX is blocking with a press-and-hold challenge, try to clear it.
        _handle_press_and_hold(page)

        # Wait for page to fully load (instead of fixed sleep)
        # Wait for items to actually render in the DOM
        try:
            page.wait_for_selector("li[data-nagish='feed-item-list-box']", timeout=15000)
        except Exception:
            pass

        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass  # Timeout is fine — page is likely loaded enough

        page.mouse.wheel(0, 1000)
        time.sleep(2)  # Brief pause for lazy-loaded items to render

        items = page.locator("li[data-nagish='feed-item-list-box']").all()
        if not items:
            items = page.locator(".feed-item").all()

        if len(items) == 0:
            logger.warning(f"[Smart Batch] Page title: {page.title()}")
            try:
                body_text = page.locator("body").inner_text()
                logger.warning(f"[Smart Batch] Body text snippet: {body_text[:500]}")
            except Exception as e:
                logger.warning(f"Could not extract body text: {e}")

        logger.info(f"[Smart Batch] Found {len(items)} items in feed.")

        for i, item in enumerate(items[:20]):
            try:
                # --- Link ---
                link_el = item.locator("a").first
                if link_el.count() == 0:
                    continue
                href = link_el.get_attribute("href")
                if not href:
                    continue
                full_link = f"https://www.yad2.co.il{href}" if href.startswith("/") else href
                ad_id = extract_ad_id(full_link)
                if not ad_id:
                    continue



                # --- Fields (using classes seen in DOM inspection) ---
                # Price: class contains 'feed-item-price_price'
                price_el = item.locator('[class*="feed-item-price_price"]').first
                price_str = price_el.inner_text().strip() if price_el.count() else "N/A"
                
                # Address/heading: class contains 'item-data-content_heading'
                heading_el = item.locator('[class*="item-data-content_heading"]').first
                address = heading_el.inner_text().strip() if heading_el.count() else ""
                
                # Info line 1 (neighborhood/city/type): class contains 'first'
                info1_el = item.locator('[class*="item-data-content_itemInfoLine"][class*="first"]').first
                city_disp = info1_el.inner_text().strip() if info1_el.count() else ""
                
                # Info line 2 (rooms/floor/size): second itemInfoLine (no 'first' class)
                info_lines = item.locator('[class*="item-data-content_itemInfoLine"]').all()
                rooms_str = ""
                for il in info_lines:
                    cls = il.get_attribute("class") or ""
                    if "first" not in cls:
                        rooms_str = il.inner_text().strip()
                        break
                
                feed_text = item.inner_text()

                # Numeric conversions for filtering
                price_numeric = int(''.join(filter(str.isdigit, price_str)) or 0)
                rooms_match = re.search(r'[\d.]+', rooms_str)
                rooms_numeric = float(rooms_match.group()) if rooms_match else -1

                if not price_numeric and not address:
                    # Probably an ad/banner item, skip it
                    continue

                ads.append({
                    'ad_id': ad_id,
                    'full_link': full_link,
                    'price': price_str,
                    'price_numeric': price_numeric,
                    'address': address,
                    'city': city_disp,
                    'rooms': rooms_str,
                    'rooms_numeric': rooms_numeric,
                    'feed_text': feed_text,
                })

            except Exception as e:
                logger.error(f"Error parsing item {i}: {e}")

    except Exception as e:
        logger.error(f"Error during master scrape: {e}")
    finally:
        try:
            page.close()
        except Exception:
            pass

    return ads


def scrape_cycle():
    logger.info("--- Starting Smart Batch Scraper Cycle ---")
    users = load_users()

    if not users:
        logger.info("No users configured.")
        return

    active_users = {uid: udata for uid, udata in users.items() if udata.get('active', True)}
    if not active_users:
        logger.info("All users paused. Skipping scrape.")
        return

    logger.info(f"[Smart Batch] 1 scrape for {len(active_users)} active user(s).")

    with sync_playwright() as p:
        context = _launch_context(p)
        try:
            ads = _scrape_all_items(context)
        finally:
            context.close()

    logger.info(f"[Smart Batch] Scraped {len(ads)} valid candidate ads.")

    # --- Fan-out: check each ad against each user ---
    total_sent = 0
    for user_id, user_data in active_users.items():
        # Skip users who haven't completed setup (no price/rooms filters set)
        user_url = user_data.get('url', '')
        if 'price=' not in user_url or 'rooms=' not in user_url:
            logger.info(f"User {user_id}: skipped (no filters set yet).")
            continue

        user_sent = 0
        user_skipped_price = 0
        user_skipped_rooms = 0
        user_skipped_keyword = 0
        user_skipped_nb = 0
        user_skipped_dedup = 0

        # Diagnostic: surface the parsed filter range so we can spot misconfigured/reversed ranges
        _dp = _parse_user_price_rooms(user_url)
        logger.info(
            f"User {user_id} filters parsed → price [{_dp[0]}-{_dp[1]}] rooms [{_dp[2]}-{_dp[3]}] | "
            f"sample ad prices: {[a.get('price_numeric') for a in ads[:5]]}"
        )

        for ad in ads:
            # Dedup check (early, cheap)
            if is_ad_notified(ad['ad_id'], user_id):
                user_skipped_dedup += 1
                continue

            # Price range
            min_price, max_price, min_rooms, max_rooms = _parse_user_price_rooms(user_data.get('url', ''))
            pn = ad['price_numeric']
            if pn > 0 and not (min_price <= pn <= max_price):
                user_skipped_price += 1
                continue

            # Rooms range
            rn = ad['rooms_numeric']
            if rn >= 0 and not (min_rooms <= rn <= max_rooms):
                user_skipped_rooms += 1
                continue

            # Keywords
            if contains_blocked_keywords(ad['feed_text'], user_data.get('keywords', '')):
                user_skipped_keyword += 1
                continue

            # Neighborhoods
            if not satisfies_neighborhood_filter(ad['feed_text'], user_data.get('neighborhoods', '')):
                user_skipped_nb += 1
                continue

            # --- Send ---
            msg = (
                f"\u200F🏠 *מציאה חדשה!*\n"
                f"\u200F📍 {ad['address']}, {ad['city']}\n"
                f"\u200F💰 {ad['price']}\n"
                f"\u200F🛏️ {ad['rooms']}\n"
                f"\u200F🔗 [לצפייה במודעה]({ad['full_link']})"
            )
            # Atomic claim before sending: prevents double-send under concurrent scrapers
            if not mark_if_new(ad['ad_id'], user_id):
                user_skipped_dedup += 1
                continue
            try:
                markup = types.InlineKeyboardMarkup()
                btn_save = types.InlineKeyboardButton(
                    "⭐ שמור דירה",
                    callback_data=f"save_ad_{ad['ad_id']}_{ad['price_numeric']}"
                )
                markup.add(btn_save)
                bot.send_message(user_id, msg, parse_mode="Markdown", disable_web_page_preview=True, reply_markup=markup)
                user_sent += 1
                total_sent += 1
            except Exception as e:
                logger.error(f"Failed to send ad {ad['ad_id']} to user {user_id}: {e}")

        logger.info(
            f"User {user_id}: sent={user_sent} | "
            f"dedup={user_skipped_dedup} | price={user_skipped_price} | "
            f"rooms={user_skipped_rooms} | kw={user_skipped_keyword} | nb={user_skipped_nb}"
        )

    logger.info(f"[Smart Batch] Cycle complete. Total alerts sent: {total_sent}")


def _sleep_until_morning():
    """Sleep until 07:00 Israel time."""
    now = datetime.now()
    wake = now.replace(hour=7, minute=0, second=0, microsecond=0)
    if now >= wake:
        wake = wake.replace(day=wake.day + 1)
    seconds = (wake - now).total_seconds()
    logger.info(f"Yad2 night mode: sleeping {int(seconds // 3600)}h {int((seconds % 3600) // 60)}m until 07:00.")
    time.sleep(seconds)


def run_scraper():
    while True:
        if 0 <= datetime.now().hour < 7:
            _sleep_until_morning()

        try:
            scrape_cycle()
        except Exception as e:
            logger.critical(f"Critical Scraper Error: {e}")

        sleep_time = random.randint(MIN_SLEEP, MAX_SLEEP)
        logger.info(f"Sleeping for {sleep_time // 60} minutes ({sleep_time}s)...")
        time.sleep(sleep_time)
