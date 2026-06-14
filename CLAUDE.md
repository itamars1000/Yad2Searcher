# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A Telegram bot that monitors Israeli rental listings and pushes per-user filtered alerts in near-real-time. Two scrapers feed it: **Yad2** (a stealth-patched Chromium driven by `patchright`, falling back to Playwright) and **Facebook groups** (Apify actor + Google Gemini for parsing). State lives in a local SQLite file. It runs as a single long-lived process / single Docker container; there is no web server and no external API surface.

## Commands

```bash
# Install (local, non-Docker)
pip install -r requirements.txt
patchright install chromium      # stealth Chromium for the Yad2 scraper (patchright is preferred)
playwright install chromium      # fallback browser if patchright isn't used. Docker base image already has Playwright's.

# Run everything (bot + both scrapers + maintenance, all as daemon threads)
python bot_engine.py

# Tests — a plain print-based script, NOT pytest/unittest. Eyeball the "Expected:" notes in the output.
python test_filters.py

# Docker (how it's actually deployed — GCP Compute Engine)
docker build -t aptsearcher .
docker run -d --env-file .env aptsearcher
```

There is no linter, formatter, type checker, or CI configured. `test_filters.py` only covers `contains_blocked_keywords` and `satisfies_neighborhood_filter` in `utils.py`; everything else (scraping, DB, Telegram flows) is verified manually.

## Configuration

Secrets come from a `.env` file (git-ignored) loaded by `config.py`. **Importing almost any module triggers `config.py`, which raises immediately if `TELEGRAM_TOKEN` or `APIFY_TOKEN` is unset** — so a `.env` is required even to run `test_filters.py` indirectly or to import scraper code.

| Var | Required | Purpose |
|---|---|---|
| `TELEGRAM_TOKEN` | yes (raises) | Telegram bot token |
| `APIFY_TOKEN` | yes (raises) | Apify actor for Facebook scraping |
| `GEMINI_API_KEY` | warns | Gemini parsing of Facebook posts |
| `ADMIN_CHAT_ID` | optional | Recipient of the daily heartbeat |
| `PAYBOX_LINK` | optional | Payment link shown in bot |

Non-secret knobs are constants in `config.py`: `ENABLE_FACEBOOK_SCRAPER`, scrape intervals (`MIN_SLEEP`/`MAX_SLEEP`, `FB_MIN_SLEEP`/`FB_MAX_SLEEP`), `MASTER_SCRAPE_URL`, `CITIES`, `FACEBOOK_GROUPS`. The Docker image pins `TZ=Asia/Jerusalem`; scraper "night mode" and Hebrew date parsing assume Israel local time, so timezone matters.

A few extra env vars tune the Yad2 browser (read in `scraper.py`): `HEADFUL=1` runs the browser headful, `BROWSER_CHANNEL=chrome` uses real Chrome instead of bundled Chromium (only if Chrome is installed), and `PROXY_SERVER` (+ optional `PROXY_USERNAME`/`PROXY_PASSWORD`) routes the scrape through a proxy — the durable fix for the datacenter-IP block (see Yad2 anti-bot below). All are no-ops when unset. Docker runs **headless** by default — headful via `xvfb-run` hung in the Playwright base image (xvfb-run brought up Xvfb but never launched Python, so the bot silently never started). Only revisit headful with a custom entrypoint that starts Xvfb explicitly, not `xvfb-run`.

## Architecture

`bot_engine.py` is the entry point. It calls `init_db()` then starts four **daemon threads**, all sharing one process and one SQLite file:

1. `run_bot` (`bot.py`) — Telegram polling loop; the conversational filter-setup wizard, saved-apartments UI, account deletion.
2. `run_scraper` (`scraper.py`) — Yad2 loop, ~30 min cadence.
3. `run_facebook_scraper` (`facebook_scraper.py`) — Facebook loop, ~60 min cadence; only if `ENABLE_FACEBOOK_SCRAPER`.
4. `run_daily_maintenance` (`bot_engine.py`) — every 24h prunes notifications >60 days and sends the admin heartbeat.

`config.py` is shared mutable state, not just constants: it owns the singleton `bot = telebot.TeleBot(...)` instance that every thread sends through, and the in-memory `user_data` dict used to track mid-conversation wizard steps.

### Smart batching (the central design idea)

Do **not** scrape once per user. Each cycle does **one** Yad2 scrape against `MASTER_SCRAPE_URL` (all of Tel Aviv, newest-first, no price/room filter), then fans the results out to every active user, applying that user's filters in Python. A user's price/rooms preferences are encoded in the Yad2 `url` string stored in their DB row; `_parse_user_price_rooms()` re-parses them at filter time, and `_ad_matches_user()` (`scraper.py`) applies price → rooms → blocked keywords → neighborhoods → dedup. Rationale: the browser scrape is the expensive part; per-user filtering is cheap CPU. If you add a filter dimension, extend `_ad_matches_user`, not the scrape.

### Yad2 anti-bot (PerimeterX)

Yad2 is behind PerimeterX, and the bot runs from a datacenter IP, so blocking is the standing risk (symptom: `Found 0 items` in `bot.log`, plus a captured page-title/body snippet showing the challenge). The Yad2 scraper mitigates this for free: `patchright` (stealth-patched Chromium) instead of vanilla headless, a **persistent context** (`.pw_profile/`) so the PerimeterX `_px3` cookie survives between cycles, no hardcoded User-Agent (avoids UA↔fingerprint mismatch), and a best-effort `_handle_press_and_hold()` for the "press & hold" challenge. (Runs headless in Docker — headful via `xvfb-run` was unreliable in this base image.) In production this did **not** beat it: PerimeterX served the hard block page (`אבטחת אתר | יד2`) with no `#px-captcha` challenge to solve, confirming an IP-reputation block. The durable fix is therefore a **residential proxy**, wired via the `PROXY_SERVER`/`PROXY_USERNAME`/`PROXY_PASSWORD` env vars (applied in `_launch_context`); a datacenter proxy won't help — it must be residential/mobile. Don't re-add a static `user_agent` or switch back to a fresh `new_context` per cycle; both regress the stealth.

### Deduplication & concurrency invariant

Multiple threads write the same SQLite DB, so it runs in **WAL mode with `synchronous=NORMAL`** (`init_db`). Dedup is per (ad, user): `mark_if_new(ad_id, user_id)` does an atomic `INSERT OR IGNORE` and returns whether the row was newly claimed. **Claim the ad with `mark_if_new` and only send the Telegram message if it returns true** — calling `is_ad_notified` then sending then inserting would race across the two scraper threads and double-notify. Preserve this ordering when touching notification code.

### Schema & migrations

Tables: `users` (user_id, url, active, keywords, city, neighborhoods), `notifications` ((ad_id,user_id) PK + created_at), `saved_apartments`, `invite_codes`. `init_db()` self-migrates by attempting `ALTER TABLE ... ADD COLUMN` inside try/except, and imports a legacy `users.json` into SQLite (renaming it `.bak`) if present. To add a column, follow the same idempotent try/except pattern rather than editing the `CREATE TABLE`.

### Hebrew text handling (`utils.py`)

Listing text is Hebrew, so several filters are language-aware and worth understanding before editing:
- **Neighborhood filter is "benefit of the doubt"**: with a whitelist set, an ad passes if it names one of the user's neighborhoods OR names no recognized neighborhood at all; it's rejected only when it names a *different* known neighborhood. It also strips Hebrew prefixes (ב/ל/ה) when matching. The expected behaviors are pinned in `test_filters.py`.
- **Hebrew date parsing** handles "היום"/"אתמול"/"לפני X שעות" and dd/mm/yy; used to drop listings older than the recent window.

### Facebook path specifics (`facebook_scraper.py`)

Posts are fetched via an Apify actor (poll until the run finishes), pre-filtered with a cheap `looks_like_rental_post()` regex, then the survivors are sent to Gemini in **one batched call** (`parse_facebook_posts_batch` in `utils.py`) to extract price/rooms/is-for-rent — batching is deliberate to conserve API credits. Images are downloaded into memory and re-uploaded as a Telegram media group to dodge Facebook CDN blocking. After matching, it reuses the same `_ad_matches_user` filtering and `mark_if_new` dedup as the Yad2 path.
