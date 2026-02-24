# 🏠 Yad2 Apartment Searcher Bot

Telegram bot that monitors [Yad2](https://www.yad2.co.il) — Israel's largest real estate platform — and instantly notifies you when new rental apartments matching your criteria are posted.

## 💡 The Problem

Finding an apartment in Israel is competitive. Good deals disappear within hours. Manually refreshing Yad2 all day isn't practical — so this bot does it for you.

## 🔍 How It Works

The bot runs two parallel processes:

1. **Telegram Bot** — A conversational interface where users set their search preferences (city, price range, rooms)
2. **Web Scraper** — A headless browser (Playwright) that visits Yad2 every ~30 minutes, extracts listings, and compares them against what's already been sent

```
User sets filters via Telegram
        ↓
Scraper fetches Yad2 listings (sorted by newest first)
        ↓
Filters by date (last 3 days only)
        ↓
Checks against SQLite DB to avoid duplicates
        ↓
Sends new matches as Telegram notifications with:
  📍 Address  💰 Price  🛏️ Rooms  🔗 Link
```

## ⚙️ Key Features

- **Smart date filtering** — Parses Hebrew dates ("היום", "אתמול") and standard formats (dd/mm/yy), with image URL fallback for ads missing date elements
- **Stealth scraping** — Uses browser fingerprint randomization and stealth plugins to avoid bot detection
- **Retry logic** — Automatically retries failed page loads (3 attempts with backoff)
- **Per-user filters** — Each Telegram user configures their own city, price & room preferences
- **Deduplication** — SQLite database tracks every ad sent to every user — no duplicates ever

## 🏗️ Architecture

| Module | Responsibility |
|---|---|
| `bot_engine.py` | Entry point — launches bot & scraper threads |
| `config.py` | Environment variables, logging, constants |
| `database.py` | SQLite operations — users table & notification history |
| `bot.py` | Telegram command handlers & filter setup wizard |
| `scraper.py` | Playwright-based Yad2 scraping & notification logic |
| `utils.py` | Date parsing, URL construction, UI helpers |

## 🏙️ Supported Cities

תל אביב · רמת גן · גבעתיים · הרצליה · חיפה · ירושלים · ראשון לציון

## 🛠️ Tech Stack

- **Python 3.10+** with multi-threading
- **Playwright** + `playwright-stealth` for web scraping
- **pyTelegramBotAPI** for the Telegram interface
- **SQLite** for persistent storage
- **Docker** for deployment (runs on GCP Compute Engine)
