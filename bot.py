import os
import time
import signal
import logging
import sys
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.error import Conflict
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# --- Configuration ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
FOOTBALL_API_KEY = os.environ.get("FOOTBALL_API_KEY")

# --- Retry settings for Conflict errors ---
MAX_RETRIES = 5
RETRY_DELAY_SECONDS = 15

# --- Logging ---
logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

# --- Football API helpers ---
FOOTBALL_API_BASE = "https://api.football-data.org/v4"


def get_teams():
    """Fetch a list of teams from the API."""
    headers = {"X-Auth-Token": FOOTBALL_API_KEY}
    try:
        resp = requests.get(
            f"{FOOTBALL_API_BASE}/competitions/PL/teams",
            headers=headers,
            timeout=10,
        )
        resp.raise_for_status()
        teams = resp.json().get("teams", [])
        return [(t["name"], t["id"]) for t in teams]
    except requests.RequestException as e:
        logger.error(f"API error while fetching teams: {e}")
        return []


def get_latest_match(team_id):
    """Fetch the latest finished match for a given team."""
    headers = {"X-Auth-Token": FOOTBALL_API_KEY}
    try:
        resp = requests.get(
            f"{FOOTBALL_API_BASE}/teams/{team_id}/matches",
            headers=headers,
            params={"status": "FINISHED", "limit": 1},
            timeout=10,
        )
        resp.raise_for_status()
        matches = resp.json().get("matches", [])
        return matches[0] if matches else None
    except requests.RequestException as e:
        logger.error(f"API error while fetching match: {e}")
        return None


# --- Telegram handlers ---
async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Send a message with an inline keyboard of teams."""
    teams = get_teams()
    if not teams:
        await update.message.reply_text(
            "Could not load teams. Please try again later."
        )
        return

    keyboard = []
    row = []
    for name, team_id in teams[:10]:
        row.append(InlineKeyboardButton(name, callback_data=f"team_{team_id}"))
        if len(row) == 2:
            keyboard.append(row)
            row = []
    if row:
        keyboard.append(row)

    reply_markup = InlineKeyboardMarkup(keyboard)
    await update.message.reply_text(
        "⚽ Select a team to see its latest match:",
        reply_markup=reply_markup,
    )


async def team_selected(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle team selection callback."""
    query = update.callback_query
    await query.answer()

    team_id = query.data.replace("team_", "")
    match = get_latest_match(team_id)

    if not match:
        await query.edit_message_text("No recent match found for this team.")
        return

    home = match["homeTeam"]["name"]
    away = match["awayTeam"]["name"]
    score = match["score"]["fullTime"]
    date = match["utcDate"][:10]

    text = (
        f"🏟️ *Latest Match*\n\n"
        f"*{home}* vs *{away}*\n"
        f"📅 Date: {date}\n"
        f"📊 Score: {score['home']} - {score['away']}"
    )
    await query.edit_message_text(text, parse_mode="Markdown")


# --- Application builder ---
def build_application() -> Application:
    """Create a fresh Application with all handlers registered."""
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", start))
    application.add_handler(
        CallbackQueryHandler(team_selected, pattern=r"^team_")
    )
    return application


# --- Graceful shutdown ---
_shutdown_requested = False


def _handle_sigterm(signum, frame):
    """Mark that we should stop after the current polling session."""
    global _shutdown_requested
    _shutdown_requested = True
    logger.info("SIGTERM received — will stop after current polling cycle.")


# --- Entry point ---
def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is not set.")
    if not FOOTBALL_API_KEY:
        raise RuntimeError("FOOTBALL_API_KEY environment variable is not set.")

    # Install SIGTERM handler so Render's shutdown signal is respected.
    signal.signal(signal.SIGTERM, _handle_sigterm)
    signal.signal(signal.SIGINT, _handle_sigterm)

    attempt = 0
    while attempt < MAX_RETRIES and not _shutdown_requested:
        attempt += 1
        logger.info(f"Starting polling (attempt {attempt}/{MAX_RETRIES})...")

        # Build a fresh Application each attempt — reusing one after a
        # Conflict can leave internal state in a bad way.
        application = build_application()

        try:
            # Force-clear any stale webhook/polling session on Telegram's side.
            # This is harmless if nothing is set and helps resolve stuck conflicts.
            try:
                application.bot.delete_webhook(drop_pending_updates=True)
            except Exception as e:
                logger.warning(f"Could not clear webhook on startup: {e}")

            application.run_polling(
                drop_pending_updates=True,
                allowed_updates=Update.ALL_TYPES,
            )
            # run_polling() returns normally when stopped (e.g. via SIGTERM).
            logger.info("Polling stopped cleanly.")
            break

        except Conflict as e:
            logger.warning(
                f"Conflict detected (attempt {attempt}/{MAX_RETRIES}): {e}"
            )
            if attempt >= MAX_RETRIES:
                logger.error("Max retries reached. Exiting.")
                sys.exit(1)
            logger.info(
                f"Waiting {RETRY_DELAY_SECONDS}s for the old instance to shut down..."
            )
            time.sleep(RETRY_DELAY_SECONDS)

        except Exception as e:
            logger.exception(f"Unexpected error during polling: {e}")
            sys.exit(1)

    logger.info("MatchPulse Bot has shut down.")


if __name__ == "__main__":
    main()
