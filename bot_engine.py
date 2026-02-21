import time
import threading
from config import logger
from database import init_db
from bot import run_bot
from scraper import run_scraper

# --- Main Engine ---
if __name__ == "__main__":
    init_db()
    
    # Thread 1: Telegram Bot
    t1 = threading.Thread(target=run_bot, daemon=True)
    t1.start()
    
    # Thread 2: Scraper Loop
    t2 = threading.Thread(target=run_scraper, daemon=True)
    t2.start()
    
    logger.info("� Bot engine started. Press Ctrl+C to stop.")
    
    # Keep main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Stopping...")
