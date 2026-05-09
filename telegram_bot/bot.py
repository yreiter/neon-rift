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

try:
    from telethon import TelegramClient
    from telethon.errors import PhoneCodeInvalidError, SessionPasswordNeededError
    HAS_TELETHON = True
except ImportError:
    HAS_TELETHON = False
    class PhoneCodeInvalidError(Exception): pass  # noqa: E701
    class SessionPasswordNeededError(Exception): pass  # noqa: E701

load_dotenv()

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

if not HAS_TELETHON:
    logger.warning("telethon not installed — userbot features disabled. Run: pip install telethon")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

TELEGRAM_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
ANTHROPIC_API_KEY = os.environ["ANTHROPIC_API_KEY"]
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY", "")
TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")
TELEGRAM_PHONE = os.getenv("TELEGRAM_PHONE", "")
TELEGRAM_2FA_PASSWORD = os.getenv("TELEGRAM_2FA_PASSWORD", "")
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

# ---------------------------------------------------------------------------
# AI clients
# ---------------------------------------------------------------------------

claude_client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

openai_client = None
if OPENAI_API_KEY:
    try:
        from openai import OpenAI as _OpenAI
        openai_client = _OpenAI(api_key=OPENAI_API_KEY)
    except ImportError:
        logger.warning("openai package not installed — GPT support disabled. Run: pip install openai")

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

conversation_history: dict[int, list[dict]] = defaultdict(list)
user_model: dict[int, str] = defaultdict(lambda: "gpt")
registered_groups: dict[str, int] = {}  # fallback: friendly_name -> bot-visible chat_id

userbot: Optional["TelegramClient"] = None
_auth_pending: dict[int, dict] = {}  # user_id -> auth flow state dict

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_authorized(user_id: int) -> bool:
    if not allowed_user_ids:
        return True
    return user_id in allowed_user_ids


def get_user_id(update: Update) -> Optional[int]:
    if update.effective_user:
        return update.effective_user.id
    return None

# ---------------------------------------------------------------------------
# Basic commands
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
        "• /login — חבר את הבוט לחשבון הטלגרם שלך\n"
        "• /mygroups — רשימת כל הקבוצות שלך\n"
        "• /send <קבוצה> | <הודעה> — שלח הודעה לקבוצה\n"
        "• /addgroup <שם> — רשום קבוצה ידנית (מתוך הקבוצה)\n"
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

    userbot_status = "✅ מחובר" if (userbot and userbot.is_connected()) else "❌ לא מחובר — השתמש ב-/login"
    await update.message.reply_text(
        "🤖 *עוזר AI — עזרה מורחבת*\n\n"
        f"*בוט אישי (Userbot):* {userbot_status}\n\n"
        "*מודלים:*\n"
        "• `/claude` — Claude Opus (Anthropic)\n"
        "• `/gpt` — GPT-4o (OpenAI)\n\n"
        "*תזכורות:*\n"
        "• `/remind 30m קנה חלב` — תזכורת בעוד 30 דקות\n"
        "• `/remind 2h פגישה` — תזכורת בעוד שעתיים\n"
        "• `/remind 1d חידוש מנוי` — תזכורת בעוד יום\n"
        "• `/reminders` — תזכורות פעילות\n\n"
        "*קבוצות דרך חשבון אישי (מומלץ):*\n"
        "1\\. קבל API מ-my\\.telegram\\.org/apps\n"
        "2\\. הגדר TELEGRAM\\_API\\_ID, TELEGRAM\\_API\\_HASH ב-\\.env\n"
        "3\\. `/login` — אימות חד-פעמי\n"
        "4\\. `/mygroups` — ראה את כל הקבוצות\n"
        "5\\. `/send תזונה | ארוחת הצהריים: פסטה`\n\n"
        "*קבוצות דרך הוספת הבוט (חלופה):*\n"
        "1\\. הוסף את הבוט לקבוצה\n"
        "2\\. `/addgroup תזונה` — רשום אותה\n"
        "3\\. `/send תזונה | הודעה`",
        parse_mode=constants.ParseMode.MARKDOWN_V2,
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
        "🟣 עברת ל-*Claude* (Anthropic). ההיסטוריה אופסה.",
        parse_mode=constants.ParseMode.MARKDOWN,
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
        "🟢 עברת ל-*ChatGPT* (OpenAI GPT-4o). ההיסטוריה אופסה.",
        parse_mode=constants.ParseMode.MARKDOWN,
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
        lines.append(f"{i}. {text}")
    await update.message.reply_text("\n".join(lines), parse_mode=constants.ParseMode.MARKDOWN)

# ---------------------------------------------------------------------------
# Userbot (Telethon)
# ---------------------------------------------------------------------------

async def init_userbot() -> None:
    global userbot
    if not HAS_TELETHON or not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        return

    async def _connect() -> None:
        global userbot
        client = TelegramClient("userbot", TELEGRAM_API_ID, TELEGRAM_API_HASH)
        await client.connect()
        if await client.is_user_authorized():
            userbot = client
            me = await client.get_me()
            logger.info("Userbot connected as %s", getattr(me, "first_name", "?"))
        else:
            await client.disconnect()
            logger.info("Userbot not authenticated. Use /login to authenticate.")

    try:
        await asyncio.wait_for(_connect(), timeout=10)
    except asyncio.TimeoutError:
        logger.warning("Userbot connection timed out — bot starting without userbot. Use /login later.")
    except Exception as e:
        logger.warning("Userbot init failed: %s — continuing without userbot.", e)


async def _send_otp(update: Update, user_id: int, phone: str) -> None:
    client = TelegramClient("userbot", TELEGRAM_API_ID, TELEGRAM_API_HASH)
    await client.connect()
    try:
        sent = await client.send_code_request(phone)
        _auth_pending[user_id] = {
            "step": "awaiting_code",
            "client": client,
            "phone": phone,
            "phone_code_hash": sent.phone_code_hash,
        }
        await update.message.reply_text(
            "📲 קוד אימות נשלח לטלגרם שלך.\n"
            "שלח את הקוד שקיבלת (ספרות בלבד):"
        )
    except Exception as e:
        await client.disconnect()
        await update.message.reply_text(f"❌ שגיאה בשליחת קוד: {e}")


async def login_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    global userbot
    user_id = get_user_id(update)
    if user_id is None or not is_authorized(user_id):
        return

    if not HAS_TELETHON:
        await update.message.reply_text("❌ חבילת telethon לא מותקנת. הרץ: pip install telethon")
        return

    if not TELEGRAM_API_ID or not TELEGRAM_API_HASH:
        await update.message.reply_text(
            "❌ TELEGRAM_API_ID ו-TELEGRAM_API_HASH לא הוגדרו.\n\n"
            "איך מקבלים:\n"
            "1. כנס ל-my.telegram.org/apps\n"
            "2. צור אפליקציה חדשה\n"
            "3. הוסף את api_id ו-api_hash ל-.env"
        )
        return

    # Cleanup any stale pending auth for this user
    if user_id in _auth_pending:
        old_client = _auth_pending[user_id].get("client")
        if old_client:
            try:
                await old_client.disconnect()
            except Exception:
                pass
        del _auth_pending[user_id]

    if userbot and userbot.is_connected() and await userbot.is_user_authorized():
        me = await userbot.get_me()
        name = getattr(me, "first_name", "?")
        await update.message.reply_text(
            f"✅ הבוט האישי כבר מחובר בתור *{name}*.",
            parse_mode=constants.ParseMode.MARKDOWN,
        )
        return

    if TELEGRAM_PHONE:
        await _send_otp(update, user_id, TELEGRAM_PHONE)
    else:
        _auth_pending[user_id] = {"step": "awaiting_phone"}
        await update.message.reply_text(
            "📱 שלח את מספר הטלפון שלך:\n(כולל קידומת מדינה, לדוג׳: +972501234567)"
        )


async def _handle_auth_step(update: Update, user_id: int, text: str) -> bool:
    """Handle in-progress userbot auth. Returns True if the message was consumed."""
    global userbot
    state = _auth_pending.get(user_id)
    if not state:
        return False

    step = state["step"]

    if step == "awaiting_phone":
        phone = text.strip()
        if not re.match(r"^\+\d{7,15}$", phone):
            await update.message.reply_text("❌ מספר לא חוקי. שלח בפורמט: +972501234567")
            return True
        await _send_otp(update, user_id, phone)
        return True

    if step == "awaiting_code":
        code = re.sub(r"[\s\-]", "", text.strip())
        client: "TelegramClient" = state["client"]
        phone = state["phone"]
        phone_code_hash = state["phone_code_hash"]
        try:
            await client.sign_in(phone=phone, code=code, phone_code_hash=phone_code_hash)
            userbot = client
            del _auth_pending[user_id]
            me = await userbot.get_me()
            name = getattr(me, "first_name", "?")
            await update.message.reply_text(
                f"✅ חובר בהצלחה בתור *{name}*!\n"
                "עכשיו תוכל להשתמש ב-/mygroups ו-/send.",
                parse_mode=constants.ParseMode.MARKDOWN,
            )
        except SessionPasswordNeededError:
            if TELEGRAM_2FA_PASSWORD:
                await client.sign_in(password=TELEGRAM_2FA_PASSWORD)
                userbot = client
                del _auth_pending[user_id]
                me = await userbot.get_me()
                name = getattr(me, "first_name", "?")
                await update.message.reply_text(
                    f"✅ חובר בהצלחה בתור *{name}*!",
                    parse_mode=constants.ParseMode.MARKDOWN,
                )
            else:
                _auth_pending[user_id]["step"] = "awaiting_password"
                await update.message.reply_text("🔒 שלח את סיסמת האימות הדו-שלבי שלך:")
        except PhoneCodeInvalidError:
            await update.message.reply_text("❌ קוד שגוי. נסה שוב:")
        except Exception as e:
            await client.disconnect()
            del _auth_pending[user_id]
            await update.message.reply_text(f"❌ שגיאת אימות: {e}")
        return True

    if step == "awaiting_password":
        client: "TelegramClient" = state["client"]
        try:
            await client.sign_in(password=text.strip())
            userbot = client
            del _auth_pending[user_id]
            me = await userbot.get_me()
            name = getattr(me, "first_name", "?")
            await update.message.reply_text(
                f"✅ חובר בהצלחה בתור *{name}*!",
                parse_mode=constants.ParseMode.MARKDOWN,
            )
        except Exception as e:
            await update.message.reply_text(f"❌ סיסמה שגויה: {e}")
        return True

    return False


async def mygroups_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = get_user_id(update)
    if user_id is None or not is_authorized(user_id):
        return

    if not userbot or not userbot.is_connected() or not await userbot.is_user_authorized():
        await update.message.reply_text(
            "❌ הבוט האישי לא מחובר.\nהשתמש ב-/login להתחברות."
        )
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=constants.ChatAction.TYPING)

    names = []
    async for dialog in userbot.iter_dialogs(limit=200):
        if dialog.is_group or dialog.is_channel:
            names.append(dialog.name or f"[ללא שם, ID: {dialog.id}]")

    if not names:
        await update.message.reply_text("לא נמצאו קבוצות.")
        return

    header = "📋 *הקבוצות שלך:*\n"
    body = "\n".join(f"• {n}" for n in names)
    for chunk in _split_message(header + body):
        await update.message.reply_text(chunk, parse_mode=constants.ParseMode.MARKDOWN)


async def _find_userbot_chat(name: str):
    """Return the first dialog entity whose name fuzzy-matches `name`."""
    name_lower = name.lower().strip()
    async for dialog in userbot.iter_dialogs(limit=200):
        dialog_name = (dialog.name or "").lower()
        if name_lower == dialog_name or name_lower in dialog_name or dialog_name in name_lower:
            return dialog.entity
    return None

# ---------------------------------------------------------------------------
# Group messaging (bot-level fallback when userbot is unavailable)
# ---------------------------------------------------------------------------

def _find_registered_group(query: str) -> Optional[int]:
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
            "❌ פקודה זו חייבת להישלח *מתוך קבוצה*.\n\n"
            "לגישה לכל הקבוצות שלך ללא הוספת בוט: /login",
            parse_mode=constants.ParseMode.MARKDOWN,
        )
        return

    if not context.args:
        await update.message.reply_text("שימוש: /addgroup <שם_ידידותי>")
        return

    group_name = " ".join(context.args).strip()
    registered_groups[group_name.lower()] = chat.id
    await update.message.reply_text(
        f"✅ הקבוצה נרשמה בשם: *{group_name}*\n`/send {group_name} | הודעה`",
        parse_mode=constants.ParseMode.MARKDOWN,
    )


async def groups_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = get_user_id(update)
    if user_id is None or not is_authorized(user_id):
        return

    if not registered_groups:
        await update.message.reply_text(
            "אין קבוצות רשומות ידנית.\n\n"
            "לגישה לכל הקבוצות שלך: /login ואז /mygroups"
        )
        return

    lines = ["📋 *קבוצות רשומות:*"] + [f"• {n}" for n in registered_groups]
    await update.message.reply_text("\n".join(lines), parse_mode=constants.ParseMode.MARKDOWN)


async def send_command(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    user_id = get_user_id(update)
    if user_id is None or not is_authorized(user_id):
        return

    if not context.args:
        await update.message.reply_text("שימוש: /send <קבוצה> | <הודעה>")
        return

    full_text = " ".join(context.args)
    if "|" not in full_text:
        await update.message.reply_text(
            "⚠️ חסר `|` בין שם הקבוצה להודעה.\n"
            "לדוגמה: /send תזונה | ארוחת הצהריים: סלט 🥗",
            parse_mode=constants.ParseMode.MARKDOWN,
        )
        return

    group_query, _, message_text = full_text.partition("|")
    group_query = group_query.strip()
    message_text = message_text.strip()

    if not message_text:
        await update.message.reply_text("❌ ההודעה ריקה.")
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=constants.ChatAction.TYPING)

    # Prefer userbot — can reach any group the user is a member of
    if userbot and userbot.is_connected() and await userbot.is_user_authorized():
        entity = await _find_userbot_chat(group_query)
        if entity is None:
            await update.message.reply_text(
                f"❌ קבוצה לא נמצאה: *{group_query}*\n"
                "בדוק את השם עם /mygroups",
                parse_mode=constants.ParseMode.MARKDOWN,
            )
            return
        try:
            await userbot.send_message(entity, message_text)
            await update.message.reply_text(
                f"✅ ההודעה נשלחה לקבוצה *{group_query}*.",
                parse_mode=constants.ParseMode.MARKDOWN,
            )
        except Exception as e:
            logger.error("Userbot send failed for %s: %s", group_query, e)
            await update.message.reply_text(f"❌ שגיאה בשליחה: {e}")
        return

    # Fallback: bot-level registered groups (bot must be a member of the group)
    chat_id = _find_registered_group(group_query)
    if chat_id is None:
        names = "\n".join(f"• {n}" for n in registered_groups) if registered_groups else "אין קבוצות רשומות"
        await update.message.reply_text(
            f"❌ קבוצה לא נמצאה: *{group_query}*\n\n"
            f"קבוצות זמינות:\n{names}\n\n"
            "לגישה לכל הקבוצות שלך: /login",
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
        logger.error("Bot send failed for %s (chat_id=%s): %s", group_query, chat_id, e)
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

    # Auth flow takes priority over normal chat
    if user_id in _auth_pending:
        await _handle_auth_step(update, user_id, user_text.strip())
        return

    await context.bot.send_chat_action(chat_id=update.effective_chat.id, action=constants.ChatAction.TYPING)

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
# Startup / shutdown
# ---------------------------------------------------------------------------

async def on_startup(app: Application) -> None:
    await init_userbot()


async def on_shutdown(app: Application) -> None:
    global userbot
    if userbot and userbot.is_connected():
        await userbot.disconnect()
        logger.info("Userbot disconnected.")


def main() -> None:
    app = (
        Application.builder()
        .token(TELEGRAM_TOKEN)
        .post_init(on_startup)
        .post_shutdown(on_shutdown)
        .build()
    )

    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(CommandHandler("help", help_command))
    app.add_handler(CommandHandler("clear", clear_command))
    app.add_handler(CommandHandler("claude", claude_command))
    app.add_handler(CommandHandler("gpt", gpt_command))
    app.add_handler(CommandHandler("remind", remind_command))
    app.add_handler(CommandHandler("reminders", reminders_command))
    app.add_handler(CommandHandler("login", login_command))
    app.add_handler(CommandHandler("mygroups", mygroups_command))
    app.add_handler(CommandHandler("addgroup", addgroup_command))
    app.add_handler(CommandHandler("groups", groups_command))
    app.add_handler(CommandHandler("send", send_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot is starting...")
    app.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == "__main__":
    main()
