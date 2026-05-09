import asyncio
import logging
import os
import re
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
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
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

claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

openai_client = None
if OPENAI_API_KEY:
    try:
        from openai import OpenAI as _OpenAI
        openai_client = _OpenAI(api_key=OPENAI_API_KEY)
    except ImportError:
        logger.warning("openai package not installed — GPT support disabled. Run: pip install openai")

# Per-user conversation history: user_id -> list of messages
conversation_history: dict[int, list[dict]] = defaultdict(list)

# Per-user model preference: "claude" or "gpt"
user_model: dict[int, str] = defaultdict(lambda: "claude")

# Registered groups: lowercase name -> chat_id
registered_groups: dict[str, int] = {}


def is_authorized(user_id: int) -> bool:
    if not allowed_user_ids:
        return True
    return user_id in allowed_user_ids


def get_user_id(update: Update) -> Optional[int]:
    if update.effective_user:
        return update.effective_user.id
    return None


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = get_user_id(update)
    if user_id is None:
        return
    if not is_authorized(user_id):
        await update.message.reply_text("⛔ אין לך הרשאה להשתמש בבוט הזה.")
        return

    conversation_history[user_id].clear()
    gpt_note = " ו-ChatGPT" if openai_client else ""
    await update.message.reply_text(
        f"👋 *שלום! אני עוזר AI אישי מבוסס Claude{gpt_note}.*\n\n"
        "שלח לי הודעה ואני אענה לך.\n\n"
        "*פקודות:*\n"
        "• /start — שיחה חדשה\n"
        "• /clear — נקה היסטוריה\n"
        "• /claude — עבור ל-Claude\n"
        "• /gpt — עבור ל-ChatGPT\n"
        "• /remind <זמן> <טקסט> — תזכורת (30m / 2h / 1d)\n"
        "• /reminders — תזכורות פעילות\n"
        "• /addgroup <שם> — רשום קבוצה (מתוך הקבוצה)\n"
        "• /groups — קבוצות רשומות\n"
        "• /send <קבוצה> | <הודעה> — שלח לקבוצה\n"
        "• /help — עזרה מורחבת",
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
        "🤖 *עוזר AI — עזרה מורחבת*\n\n"
        "*מודלים:*\n"
        "• `/claude` — Claude Opus (Anthropic) — חשיבה עמוקה\n"
        "• `/gpt` — GPT-4o (OpenAI) — מהיר ומגוון\n\n"
        "*תזכורות:*\n"
        "• `/remind 30m קנה חלב` — תזכורת בעוד 30 דקות\n"
        "• `/remind 2h פגישה` — תזכורת בעוד שעתיים\n"
        "• `/remind 1d חידוש מנוי` — תזכורת בעוד יום\n"
        "• `/reminders` — רשימת תזכורות פעילות\n\n"
        "*קבוצות:*\n"
        "1\\. הוסף את הבוט לקבוצה\n"
        "2\\. שלח `/addgroup תזונה` *מתוך הקבוצה*\n"
        "3\\. שלח `/send תזונה | ארוחת הצהריים: פסטה` מכל מקום\n"
        "• `/groups` — כל הקבוצות הרשומות",
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


async def claude_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = get_user_id(update)
    if user_id is None or not is_authorized(user_id):
        return
    user_model[user_id] = "claude"
    conversation_history[user_id].clear()
    await update.message.reply_text(
        "🟣 עברת ל\\-*Claude* \\(Anthropic\\)\\. ההיסטוריה אופסה\\.",
        parse_mode=constants.ParseMode.MARKDOWN_V2,
    )


async def gpt_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = get_user_id(update)
    if user_id is None or not is_authorized(user_id):
        return
    if not openai_client:
        await update.message.reply_text(
            "❌ GPT לא זמין.\nהוסף OPENAI_API_KEY ל-.env והתקן:\npip install openai"
        )
        return
    user_model[user_id] = "gpt"
    conversation_history[user_id].clear()
    await update.message.reply_text(
        "🟢 עברת ל\\-*ChatGPT* \\(OpenAI GPT\\-4o\\)\\. ההיסטוריה אופסה\\.",
        parse_mode=constants.ParseMode.MARKDOWN_V2,
    )


# ---------------------------------------------------------------------------
# Reminders
# ---------------------------------------------------------------------------

_TIME_UNITS = {"m": 60, "h": 3600, "d": 86400}
_UNIT_LABELS = {"m": "דקות", "h": "שעות", "d": "ימים"}


def _parse_remind_seconds(time_str: str) -> Optional[int]:
    m = re.fullmatch(r"(\d+)([mhd])", time_str.strip().lower())
    if not m:
        return None
    return int(m.group(1)) * _TIME_UNITS[m.group(2)]


async def _fire_reminder(context: ContextTypes.DEFAULT_TYPE) -> None:
    data = context.job.data
    await context.bot.send_message(
        chat_id=data["chat_id"],
        text=f"⏰ *תזכורת:* {data['text']}",
        parse_mode=constants.ParseMode.MARKDOWN,
    )


async def remind_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = get_user_id(update)
    if user_id is None or not is_authorized(user_id):
        return

    args = context.args
    if not args or len(args) < 2:
        await update.message.reply_text(
            "שימוש: /remind <זמן> <הודעה>\n\n"
            "לדוגמה:\n"
            "• /remind 30m קנה חלב\n"
            "• /remind 2h פגישה עם יוסי\n"
            "• /remind 1d לחדש מנוי"
        )
        return

    delay = _parse_remind_seconds(args[0])
    if delay is None:
        await update.message.reply_text("❌ פורמט זמן לא חוקי. השתמש ב-30m, 2h, 1d וכו׳.")
        return

    reminder_text = " ".join(args[1:])
    context.job_queue.run_once(
        _fire_reminder,
        delay,
        data={"chat_id": update.effective_chat.id, "text": reminder_text},
        name=f"remind_{user_id}",
        user_id=user_id,
    )

    m = re.fullmatch(r"(\d+)([mhd])", args[0].lower())
    time_label = f"{m.group(1)} {_UNIT_LABELS[m.group(2)]}" if m else args[0]

    await update.message.reply_text(
        f"✅ תזכורת הוגדרה בעוד *{time_label}*:\n_{reminder_text}_",
        parse_mode=constants.ParseMode.MARKDOWN,
    )


async def reminders_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = get_user_id(update)
    if user_id is None or not is_authorized(user_id):
        return

    user_jobs = [j for j in context.job_queue.jobs() if j.user_id == user_id]

    if not user_jobs:
        await update.message.reply_text("אין תזכורות פעילות.")
        return

    lines = ["📋 *תזכורות פעילות:*"]
    for i, job in enumerate(user_jobs, 1):
        text = (job.data or {}).get("text", "")
        lines.append(f"{i}\\. {text}")
    await update.message.reply_text("\n".join(lines), parse_mode=constants.ParseMode.MARKDOWN)


# ---------------------------------------------------------------------------
# Group messaging
# ---------------------------------------------------------------------------

def _find_group(query: str) -> Optional[int]:
    query = query.lower().strip()
    if query in registered_groups:
        return registered_groups[query]
    for name, chat_id in registered_groups.items():
        if query in name or name in query:
            return chat_id
    return None


async def addgroup_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = get_user_id(update)
    if user_id is None or not is_authorized(user_id):
        return

    chat = update.effective_chat
    if chat.type not in ("group", "supergroup"):
        await update.message.reply_text(
            "❌ פקודה זו חייבת להישלח *מתוך קבוצה*.\n"
            "הוסף את הבוט לקבוצה ושלח שם `/addgroup שם`.",
            parse_mode=constants.ParseMode.MARKDOWN,
        )
        return

    if not context.args:
        await update.message.reply_text("שימוש: /addgroup <שם_ידידותי>\nלדוגמה: /addgroup תזונה")
        return

    group_name = " ".join(context.args).strip()
    registered_groups[group_name.lower()] = chat.id
    await update.message.reply_text(
        f"✅ הקבוצה נרשמה בשם: *{group_name}*\n"
        f"שלח הודעות עם:\n`/send {group_name} | הודעה`",
        parse_mode=constants.ParseMode.MARKDOWN,
    )


async def groups_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = get_user_id(update)
    if user_id is None or not is_authorized(user_id):
        return

    if not registered_groups:
        await update.message.reply_text(
            "אין קבוצות רשומות.\n\n"
            "*איך לרשום קבוצה:*\n"
            "1. הוסף את הבוט לקבוצה\n"
            "2. שלח `/addgroup שם` מתוך הקבוצה",
            parse_mode=constants.ParseMode.MARKDOWN,
        )
        return

    lines = ["📋 *קבוצות רשומות:*"]
    for name in registered_groups:
        lines.append(f"• {name}")
    await update.message.reply_text("\n".join(lines), parse_mode=constants.ParseMode.MARKDOWN)


async def send_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = get_user_id(update)
    if user_id is None or not is_authorized(user_id):
        return

    if not context.args:
        await update.message.reply_text(
            "שימוש: /send <קבוצה> | <הודעה>\n"
            "לדוגמה: /send תזונה | ארוחת הצהריים: סלט ירקות 🥗"
        )
        return

    full_text = " ".join(context.args)
    if "|" not in full_text:
        await update.message.reply_text(
            "⚠️ חסר מפריד `|` בין שם הקבוצה להודעה.\n"
            "לדוגמה: /send תזונה | ארוחת הצהריים: סלט",
            parse_mode=constants.ParseMode.MARKDOWN,
        )
        return

    group_query, _, message_text = full_text.partition("|")
    group_query = group_query.strip()
    message_text = message_text.strip()

    if not message_text:
        await update.message.reply_text("❌ ההודעה ריקה.")
        return

    chat_id = _find_group(group_query)
    if chat_id is None:
        names = "\n".join(f"• {n}" for n in registered_groups) if registered_groups else "אין קבוצות רשומות"
        await update.message.reply_text(
            f"❌ קבוצה לא נמצאה: *{group_query}*\n\nקבוצות זמינות:\n{names}",
            parse_mode=constants.ParseMode.MARKDOWN,
        )
        return

    try:
        await context.bot.send_message(chat_id=chat_id, text=message_text)
        await update.message.reply_text(
            f"✅ ההודעה נשלחה לקבוצה *{group_query}*.",
            parse_mode=constants.ParseMode.MARKDOWN,
        )
    except Exception as e:
        logger.error("Failed to send to group %s (chat_id=%s): %s", group_query, chat_id, e)
        await update.message.reply_text(f"❌ שגיאה בשליחה לקבוצה: {e}")


# ---------------------------------------------------------------------------
# Message handler
# ---------------------------------------------------------------------------

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

    await context.bot.send_chat_action(
        chat_id=update.effective_chat.id,
        action=constants.ChatAction.TYPING,
    )

    history = conversation_history[user_id]
    history.append({"role": "user", "content": user_text.strip()})

    if len(history) > MAX_HISTORY:
        history[:] = history[-MAX_HISTORY:]

    model = user_model[user_id]

    try:
        if model == "gpt" and openai_client:
            response_text = await asyncio.get_event_loop().run_in_executor(
                None, _call_gpt, list(history)
            )
        else:
            response_text = await asyncio.get_event_loop().run_in_executor(
                None, _call_claude, list(history)
            )
    except Exception as e:
        logger.error("AI API error (%s): %s", model, e)
        await update.message.reply_text("❌ אירעה שגיאה בתקשורת עם ה-AI. אנא נסה שוב.")
        history.pop()
        return

    history.append({"role": "assistant", "content": response_text})

    for chunk in _split_message(response_text):
        await update.message.reply_text(chunk)


# ---------------------------------------------------------------------------
# AI backends
# ---------------------------------------------------------------------------

def _call_claude(messages: list[dict]) -> str:
    response = claude_client.messages.create(
        model="claude-opus-4-7",
        max_tokens=4096,
        system=SYSTEM_PROMPT,
        messages=messages,
        thinking={"type": "adaptive"},
    )
    parts: list[str] = []
    for block in response.content:
        if block.type == "text":
            parts.append(block.text)
    return "\n".join(parts).strip()


def _call_gpt(messages: list[dict]) -> str:
    response = openai_client.chat.completions.create(
        model="gpt-4o",
        messages=[{"role": "system", "content": SYSTEM_PROMPT}] + messages,
        max_tokens=4096,
    )
    return response.choices[0].message.content.strip()


def _split_message(text: str, limit: int = 4000) -> list[str]:
    if len(text) <= limit:
        return [text]
    chunks: list[str] = []
    while text:
        if len(text) <= limit:
            chunks.append(text)
            break
        split_at = text.rfind("\n", 0, limit)
        if split_at == -1:
            split_at = limit
        chunks.append(text[:split_at])
        text = text[split_at:].lstrip("\n")
    return chunks


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> None:
    app = Application.builder().token(TELEGRAM_TOKEN).build()

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(CommandHandler("claude", claude_command))
    app.add_handler(CommandHandler("gpt", gpt_command))
    app.add_handler(CommandHandler("remind", remind_command))
    app.add_handler(CommandHandler("reminders", reminders_command))
    app.add_handler(CommandHandler("addgroup", addgroup_command))
    app.add_handler(CommandHandler("groups", groups_command))
    app.add_handler(CommandHandler("send", send_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot is starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
