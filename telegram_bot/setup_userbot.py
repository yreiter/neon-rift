#!/usr/bin/env python3
"""
One-time userbot authentication setup.

Run this script once from the terminal to authenticate with your Telegram account.
It saves a session file (userbot.session) that the bot reuses automatically on every start.

Usage:
    python setup_userbot.py
"""

import asyncio
import os
import sys

from dotenv import load_dotenv

load_dotenv()

TELEGRAM_API_ID = int(os.getenv("TELEGRAM_API_ID", "0"))
TELEGRAM_API_HASH = os.getenv("TELEGRAM_API_HASH", "")
TELEGRAM_PHONE = os.getenv("TELEGRAM_PHONE", "")
TELEGRAM_2FA_PASSWORD = os.getenv("TELEGRAM_2FA_PASSWORD", "")


def check_env() -> bool:
    missing = []
    if not TELEGRAM_API_ID:
        missing.append("TELEGRAM_API_ID")
    if not TELEGRAM_API_HASH:
        missing.append("TELEGRAM_API_HASH")
    if missing:
        print("❌ Missing in .env:", ", ".join(missing))
        print()
        print("Get them from: https://my.telegram.org/apps")
        print("  1. Log in → 'API development tools'")
        print("  2. Create an app (any name/platform)")
        print("  3. Copy api_id and api_hash into .env")
        return False
    return True


async def setup() -> None:
    try:
        from telethon import TelegramClient
        from telethon.errors import SessionPasswordNeededError
    except ImportError:
        print("❌ telethon is not installed. Run: pip install telethon")
        sys.exit(1)

    if not check_env():
        sys.exit(1)

    print("=== Telegram Userbot Setup ===")
    print()

    client = TelegramClient("userbot", TELEGRAM_API_ID, TELEGRAM_API_HASH)
    await client.connect()

    if await client.is_user_authorized():
        me = await client.get_me()
        print(f"✅ Already authenticated as {me.first_name} (@{me.username})")
        print("   userbot.session is ready — start the bot normally.")
        await client.disconnect()
        return

    phone = TELEGRAM_PHONE.strip() or input("Phone number (e.g. +972501234567): ").strip()
    print(f"Sending code to {phone} ...")
    await client.send_code_request(phone)

    code = input("Enter the code you received on Telegram: ").strip()

    try:
        await client.sign_in(phone=phone, code=code)
    except SessionPasswordNeededError:
        password = TELEGRAM_2FA_PASSWORD.strip() or input("Two-factor password: ").strip()
        await client.sign_in(password=password)

    me = await client.get_me()
    print()
    print(f"✅ Authenticated as {me.first_name} (@{me.username})")
    print("   userbot.session saved. Start the bot — it will connect automatically.")
    await client.disconnect()


if __name__ == "__main__":
    asyncio.run(setup())
