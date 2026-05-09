import asyncio
import logging
import os
from collections import defaultdict
from typing import Optional

import anthropic
from dotenv import load_dotenv
from telegram import Update, constants
from telegram.ext import (
    Application,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
MAX_HISTORY = int(os.getenv("MAX_HISTORY_MESSAGES", "40"))
ALLOWED_USERS = os.getenv("ALLOWED_USER_IDS", "")
SYSTEM_PROMPT = os.getenv(
    "SYSTEM_PROMPT",
    "You are a helpful, friendly AI assistant. "
    "Answer clearly and concisely. "
    "When the user writes in Hebrew, respond in Hebrew.",
)

allowed_user_ids: set[int] = set()
if ALLOWED_USERS.strip():
    for uid in ALLOWED_USERS.split(","):
        uid = uid.strip()
        if uid.isdigit():
            allowed_user_ids.add(int(uid))

claude = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

# Per-user conversation history: user_id -> list of messages
conversation_history: dict[int, list[dict]] = defaultdict(list)


def is_authorized(user_id: int) -> bool:
    if not allowed_user_ids:
        return True
    return user_id in allowed_user_ids


def get_user_id(update: Update) -> Optional[int]:
    if update.effective_user:
        return update.effective_user.id
    return None


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = get_user_id(update)
    if user_id is None:
        return

    if not is_authorized(user_id):
        await update.message.reply_text("⛔ אין לך הרשאה להשתמש בבוט הזה.")
        return

    conversation_history[user_id].clear()
    await update.message.reply_text(
        "👋 *שלום! אני עוזר AI אישי מבוסס Claude.*\n\n"
        "פשוט שלח לי הודעה ואני אענה לך.\n\n"
        "פקודות זמינות:\n"
        "• /start — התחל שיחה חדשה\n"
        "• /clear — נקה היסטוריית שיחה\n"
        "• /help — עזרה",
        parse_mode=constants.ParseMode.MARKDOWN,
    )


async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = get_user_id(update)
    if user_id is None:
        return

    if not is_authorized(user_id):
        await update.message.reply_text("⛔ אין לך הרשאה להשתמש בבוט הזה.")
        return

    await update.message.reply_text(
        "🤖 *עוזר AI אישי — עזרה*\n\n"
        "שלח לי כל שאלה או בקשה — אני כאן לעזור!\n\n"
        "*פקודות:*\n"
        "• `/start` — פתיחת שיחה חדשה ואיפוס ההיסטוריה\n"
        "• `/clear` — מחיקת היסטוריית השיחה הנוכחית\n"
        "• `/help` — הצגת עזרה זו\n\n"
        "*יכולות:*\n"
        "• מענה לשאלות בכל נושא\n"
        "• עזרה בכתיבה ועריכה\n"
        "• פתרון בעיות תכנות\n"
        "• תרגום טקסטים\n"
        "• ועוד הרבה...",
        parse_mode=constants.ParseMode.MARKDOWN,
    )


async def clear_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = get_user_id(update)
    if user_id is None:
        return

    if not is_authorized(user_id):
        await update.message.reply_text("⛔ אין לך הרשאה להשתמש בבוט הזה.")
        return

    conversation_history[user_id].clear()
    await update.message.reply_text("✅ היסטוריית השיחה נמחקה. נתחיל מחדש!")


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = get_user_id(update)
    if user_id is None:
        return

    if not is_authorized(user_id):
        await update.message.reply_text("⛔ אין לך הרשאה להשתמש בבוט הזה.")
        return

    user_text = update.message.text
    if not user_text or not user_text.strip():
        return

    # Show typing indicator
    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=constants.ChatAction.TYPING,
    )

    # Add user message to history
    history = conversation_history[user_id]
    history.append({"role": "user", "content": user_text.strip()})

    # Trim history to avoid exceeding context
    if len(history) > MAX_HISTORY:
        history[:] = history[-MAX_HISTORY:]

    try:
        response_text = await asyncio.get_event_loop().run_in_executor(
            None, _call_claude, list(history)
        )
    except anthropic.RateLimitError:
        await update.message.reply_text(
            "⚠️ הגעת למגבלת הקצב. אנא המתן מספר שניות ונסה שוב."
        )
        history.pop()
        return
    except anthropic.APIError as e:
        logger.error("Anthropic API error: %s", e)
        await update.message.reply_text(
            "❌ אירעה שגיאה בתקשורת עם ה-AI. אנא נסה שוב."
        )
        history.pop()
        return

    # Add assistant response to history
    history.append({"role": "assistant", "content": response_text})

    # Send response, splitting if needed (Telegram's 4096 char limit)
    for chunk in _split_message(response_text):
        await update.message.reply_text(chunk)


def _call_claude(messages: list[dict]) -> str:
    """Synchronous call to Claude API (run in executor to avoid blocking)."""
    response = claude.messages.create(
        model="claude-opus-4-7",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=messages,
        thinking={"type": "adaptive"},
    )

    # Extract text from response content blocks
    parts: list[str] = []
    for block in response.content:
        if block.type == "text":
            parts.append(block.text)

    return "\n".join(parts).strip()


def _split_message(text: str, limit: int = 4000) -> list[str]:
    """Split a long message into chunks that fit Telegram's limit."""
    if len(text) <= limit:
        return [text]

    chunks: list[str] = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        # Try to split at a newline boundary
        split_at = text.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = limit
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")

    return chunks


def main() -> None:
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot is starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
