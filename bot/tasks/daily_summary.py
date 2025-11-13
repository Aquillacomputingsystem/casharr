# bot/tasks/daily_summary.py
from discord.ext import tasks
from datetime import datetime, timezone
from bot import bot, send_admin
from database import get_all_members, parse_iso

@tasks.loop(hours=24)
async def daily_summary():
    """Send a daily summary of member stats to the admin channel."""
    rows = get_all_members()
    now = datetime.now(timezone.utc)
    active_payers = sum(1 for r in rows if parse_iso(r[10]) and parse_iso(r[10]) > now)
    active_trials = sum(1 for r in rows if parse_iso(r[8]) and parse_iso(r[8]) > now)
    expired = sum(1 for r in rows if (parse_iso(r[8]) and parse_iso(r[8]) < now) or (parse_iso(r[10]) and parse_iso(r[10]) < now))
    msg = (
        f"🧾 **Daily Summary — {datetime.now():%Y-%m-%d}**\n"
        f"👥 Total Members: {len(rows)}\n"
        f"💰 Active Payers: {active_payers}\n"
        f"🧪 Active Trials: {active_trials}\n"
        f"⚠️ Expired: {expired}"
    )
    await send_admin(msg)

@daily_summary.before_loop
async def before_summary():
    await bot.wait_until_ready()

daily_summary.start()
