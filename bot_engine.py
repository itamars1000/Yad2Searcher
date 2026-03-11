import time
import threading
from config import logger, ENABLE_FACEBOOK_SCRAPER
from database import init_db
from bot import run_bot
from scraper import run_scraper
from facebook_scraper import run_facebook_scraper

# --- Main Engine ---
if __name__ == "__main__":
    init_db()
    
    # Thread 1: Telegram Bot
    t1 = threading.Thread(target=run_bot, daemon=True)
    t1.start()
    
    # Thread 2: Yad2 Scraper Loop
    t2 = threading.Thread(target=run_scraper, daemon=True)
    t2.start()
    
    # Thread 3: Facebook Scraper Loop
    if ENABLE_FACEBOOK_SCRAPER:
        t3 = threading.Thread(target=run_facebook_scraper, daemon=True)
        t3.start()
        logger.info("📘 Facebook scraper is ENABLED.")
    else:
        logger.info("📘 Facebook scraper is DISABLED (saves credits).")
    
    logger.info("🤖 Bot engine started. Press Ctrl+C to stop.")
    
    # Keep main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Stopping...")
