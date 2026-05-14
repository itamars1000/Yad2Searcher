import time
import threading
from datetime import datetime
from config import logger, ENABLE_FACEBOOK_SCRAPER, bot, ADMIN_CHAT_ID
from database import init_db, cleanup_old_notifications
from bot import run_bot
from scraper import run_scraper
from facebook_scraper import run_facebook_scraper


def run_daily_maintenance():
    """Once every 24h: send admin heartbeat with a brief summary and prune old notifications."""
    while True:
        # Sleep first so we don't fire immediately on startup
        time.sleep(24 * 3600)
        try:
            removed = cleanup_old_notifications(days=60)
            if ADMIN_CHAT_ID:
                msg = (
                    f"💓 Heartbeat — {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
                    f"DB cleanup: removed {removed} old notifications."
                )
                try:
                    bot.send_message(ADMIN_CHAT_ID, msg)
                except Exception as e:
                    logger.error(f"Heartbeat send failed: {e}")
        except Exception as e:
            logger.error(f"Daily maintenance error: {e}")


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

    # Thread 4: Daily maintenance + admin heartbeat
    t4 = threading.Thread(target=run_daily_maintenance, daemon=True)
    t4.start()

    logger.info("🤖 Bot engine started. Press Ctrl+C to stop.")

    # Keep main thread alive
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Stopping...")
