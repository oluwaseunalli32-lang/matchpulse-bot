import os
import logging
import requests
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    ContextTypes,
)

# --- Configuration ---
BOT_TOKEN = os.environ.get("BOT_TOKEN")
FOOTBALL_API_KEY = os.environ.get("FOOTBALL_API_KEY")

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


# --- Entry point ---
def main():
    if not BOT_TOKEN:
        raise RuntimeError("BOT_TOKEN environment variable is not set.")
    if not FOOTBALL_API_KEY:
        raise RuntimeError("FOOTBALL_API_KEY environment variable is not set.")

    application = Application.builder().token(BOT_TOKEN).build()

    application.add_handler(CommandHandler("start", start))
    application.add_handler(
        CallbackQueryHandler(team_selected, pattern=r"^team_")
    )

    logger.info("MatchPulse Bot is starting (polling mode)...")
    application.run_polling(
        drop_pending_updates=True,
        allowed_updates=Update.ALL_TYPES,
    )


if __name__ == "__main__":
    main()
