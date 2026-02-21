import re
import time
import random
from datetime import datetime
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright
from playwright_stealth import Stealth

from config import bot, MIN_SLEEP, MAX_SLEEP, logger
from database import load_users, is_ad_notified, mark_ad_notified
from utils import parse_hebrew_date

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
                            date_el = item.locator('span[class*="report-ad_createdAt"]').first
                            
                            parsed_date = None
                            date_text_log = "N/A"

                            if date_el.count() > 0:
                                raw_text = date_el.inner_text()
                                date_text_log = raw_text
                                
                                match = re.search(r"(\d{1,2})/(\d{1,2})/(\d{2})", raw_text)
                                if match:
                                    day = int(match.group(1))
                                    month = int(match.group(2))
                                    year_short = int(match.group(3))
                                    year_full = 2000 + year_short
                                    
                                    parsed_date = datetime(year_full, month, day).date()
                                    logger.debug(f"Item {i}: Parsed date {parsed_date} from '{raw_text}' (Regex).")
                                else:
                                    parsed_date = parse_hebrew_date(raw_text)
                                    logger.debug(f"Item {i}: Parsed date {parsed_date} from '{raw_text}' (Fallback).")
                            else:
                                # Fallback: Try extracting date from Image URL
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
                                    pass
                            
                            if not parsed_date:
                                logger.debug(f"Ad {ad_id}: No valid date found. Skipping.")
                                no_date_count += 1
                                continue
                            
                            # 3-Day Filter
                            today = datetime.now().date()
                            delta = (today - parsed_date).days
                            
                            logger.debug(f"Ad {ad_id} | Price: {price} | Date: {parsed_date} | Age: {delta} days")

                            if delta > 3:
                                too_old_count += 1
                                continue
                            
                        except Exception as e:
                            logger.error(f"Error checking date for {ad_id}: {e}")
                            error_count += 1
                            continue

                        # New Ad Found! Extract Details
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
