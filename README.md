# 🏠 Yad2 Apartment Searcher Bot

A Telegram bot that automatically scans [Yad2](https://www.yad2.co.il) for new rental apartment listings and sends real-time notifications.

## ✨ Features

- 🔍 **Auto-scanning** — Scrapes Yad2 every ~30 minutes for new listings
- 📅 **Date filtering** — Only sends ads from the last 3 days
- 🔔 **Telegram notifications** — Instant alerts with price, location, rooms & link
- 🛡️ **Stealth mode** — Uses Playwright with stealth to avoid bot detection
- 🔄 **Deduplication** — Never sends the same ad twice
- ⚙️ **Custom filters** — Set city, price range & room count via Telegram

## 📁 Project Structure

```
├── bot_engine.py      # Entry point — starts bot & scraper threads
├── config.py          # Configuration, logging, constants
├── database.py        # SQLite: user management & notification history
├── bot.py             # Telegram bot handlers (commands, filters)
├── scraper.py         # Playwright scraping logic
├── utils.py           # Date parsing, URL construction, menu helpers
├── Dockerfile         # Docker deployment
├── requirements.txt   # Python dependencies
└── .env               # Telegram token (not in git)
```

## 🚀 Quick Start

### Prerequisites
- Python 3.10+
- A Telegram Bot Token (from [@BotFather](https://t.me/BotFather))

### Installation

```bash
# Clone the repo
git clone https://github.com/itamars1000/Yad2Searcher.git
cd Yad2Searcher

# Create virtual environment
python -m venv venv
source venv/bin/activate  # Linux/Mac
# or: .\venv\Scripts\activate  # Windows

# Install dependencies
pip install -r requirements.txt
playwright install chromium

# Set your Telegram token
echo "TELEGRAM_TOKEN=your_token_here" > .env
```

### Run

```bash
python bot_engine.py
```

### Docker

```bash
docker build -t yad2bot .
docker run -d --env-file .env --name yad2bot yad2bot
```

## 🤖 Bot Commands

| Command | Action |
|---|---|
| `/start` | Welcome message & setup wizard |
| `🚀 התחל חיפוש` | Configure city, price & rooms |
| `✅ הפעל התראות` | Enable notifications |
| `🛑 עצור התראות` | Pause (settings saved) |
| `🔍 מסנן חדש` | Change search filters |
| `/stop` | Stop notifications |

## 🏙️ Supported Cities

תל אביב · רמת גן · גבעתיים · הרצליה · חיפה · ירושלים · ראשון לציון

## ⚙️ Configuration

| Setting | Default | Location |
|---|---|---|
| Scan interval | 28-32 min | `config.py` |
| Date filter | 3 days | `scraper.py` |
| Items per scan | 15 (newest) | `scraper.py` |
| Sort order | By date (newest) | URL `order=1` |

## 📝 License

MIT
