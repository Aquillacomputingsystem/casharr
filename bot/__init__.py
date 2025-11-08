# bot/__init__.py
import os
import asyncio
import configparser
from datetime import datetime, timezone
import discord
from discord import app_commands
from loghelper import logger  # ✅ Centralized system-wide logger

# Reuse existing helpers
from database import (
    init_db, save_member, get_member, get_trial_members, get_payer_members,
    start_trial, end_trial, update_payment, get_all_for_reminders,
    mark_trial_reminder_sent, mark_paid_reminder_sent, get_all_members
)
from plexhelper import PlexHelper

# ─────────────────────────────
# Load configuration safely
# ─────────────────────────────
CONFIG_PATH = os.path.join("config", "config.ini")
config = configparser.ConfigParser()

try:
    config.read(CONFIG_PATH, encoding="utf-8")
except Exception as e:
    logger.error(f"⚠️ Failed to read config file ({CONFIG_PATH}): {e}")

# Discord settings
TOKEN = config["Discord"].get("BotToken", "")
INITIAL_ROLE = config["Discord"].get("InitialRole", "No Access")
TRIAL_ROLE = config["Discord"].get("TrialRole", "Trial")
PAYER_ROLE = config["Discord"].get("PayerRole", "Payer")
LIFETIME_ROLE = config["Discord"].get("LifetimeRole", "Lifetime")
ADMIN_ROLE = config["Discord"].get("AdminRole", "Admin")
ADMIN_CHANNEL_ID = int(config["Discord"].get("AdminChannelID", "0") or 0)

# Messages
WELCOME_MESSAGE = config["Messages"].get(
    "Welcome",
    "Welcome {user}! 👋 Please answer a few quick questions so we can set up your access."
)
TRIAL_REMINDER_MSG = config["Messages"].get(
    "TrialReminder",
    "⏰ Your trial ends on {date}. Renew:\n1m {m1}\n3m {m3}\n6m {m6}\n12m {m12}"
)
PAID_REMINDER_MSG = config["Messages"].get(
    "PaidReminder",
    "⏰ Your subscription ends on {date}. Renew:\n1m {m1}\n3m {m3}\n6m {m6}\n12m {m12}"
)

# Plex
PLEX_URL = config["Plex"].get("URL", "")
PLEX_TOKEN = config["Plex"].get("Token", "")
LIBRARIES = [x.strip() for x in config["Plex"].get("Libraries", "").split(",") if x.strip()]

# Trial
TRIAL_DAYS = int(config["Trial"].get("DurationDays", "30"))

# Site / Pricing
if "Site" in config and "Domain" in config["Site"]:
    DOMAIN = config["Site"]["Domain"].rstrip("/")
else:
    DOMAIN = "http://localhost:5000"

CURRENCY = config["Pricing"].get("DefaultCurrency", "USD").upper()
PRICES = {
    "1": float(config["Pricing"].get("1Month", "0")),
    "3": float(config["Pricing"].get("3Months", "0")),
    "6": float(config["Pricing"].get("6Months", "0")),
    "12": float(config["Pricing"].get("12Months", "0")),
}

# Reminders
REMINDERS_ENABLED = config["Reminders"].getboolean("Enabled", True)
REMINDER_DAYS = int(config["Reminders"].get("DaysBeforeExpiry", "3"))

# Paths
DB_PATH = os.path.join("data", "members.db")
EXPORTS_DIR = "exports"
os.makedirs("data", exist_ok=True)
os.makedirs(EXPORTS_DIR, exist_ok=True)

# ─────────────────────────────
# Initialize database + Plex safely
# ─────────────────────────────
init_db()

plex = None
try:
    plex = PlexHelper(PLEX_URL, PLEX_TOKEN, LIBRARIES)
    logger.info("✅ Connected to Plex successfully.")
except Exception as e:
    logger.error(f"⚠️ Failed to connect to Plex: {type(e).__name__}: {e}")
    logger.warning("Continuing without active Plex connection. Some features will be limited.")

# ─────────────────────────────
# Discord Bot Initialization
# ─────────────────────────────
intents = discord.Intents.default()
intents.members = True
intents.guilds = True
intents.message_content = True

class CasharrBot(discord.Client):
    def __init__(self):
        super().__init__(intents=intents)
        self.tree = app_commands.CommandTree(self)

client = CasharrBot()
bot = client  # alias for backward compatibility

# ─────────────────────────────
# Shared Helpers
# ─────────────────────────────
def parse_iso(dt: str | None):
    if not dt:
        return None
    try:
        return datetime.fromisoformat(dt)
    except Exception:
        return None

def pay_page(discord_id: int | str, months: str | None = None) -> str:
    base = f"{DOMAIN}/pay?discord_id={discord_id}"
    if months and months in PRICES:
        return f"{base}&months={months}"
    return base

async def send_admin(message: str):
    """Send a message to the configured admin channel, or log if unavailable."""
    if not ADMIN_CHANNEL_ID:
        logger.warning("[ADMIN] No AdminChannelID configured. Message: %s", message)
        return

    channel = bot.get_channel(ADMIN_CHANNEL_ID)
    if channel:
        try:
            await channel.send(message)
            logger.info("[ADMIN] %s", message)
        except Exception as e:
            logger.error("Failed to send admin message: %s", e)
    else:
        logger.warning("[ADMIN] Channel not found. Message: %s", message)

async def check_and_upgrade_after_invite(member: discord.Member, email: str):
    """Check Plex server access and upgrade Discord role accordingly."""
    if plex is None:
        logger.warning("Skipping Plex invite check (no active connection).")
        return

    try:
        server_name = plex.plex.friendlyName
        has_access = False

        for u in plex.account.users():
            if not u.email:
                continue
            if email.lower() == u.email.lower() and any(server_name in str(s) for s in u.servers):
                has_access = True
                break

        guild = member.guild
        trial_role = discord.utils.get(guild.roles, name=TRIAL_ROLE)
        payer_role = discord.utils.get(guild.roles, name=PAYER_ROLE)
        no_access_role = discord.utils.get(guild.roles, name=INITIAL_ROLE)

        if has_access:
            if no_access_role in member.roles and payer_role not in member.roles:
                await member.remove_roles(no_access_role)
                if trial_role:
                    await member.add_roles(trial_role)
                start_trial(member.id, TRIAL_DAYS)
                await send_admin(
                    f"🎉 {member.mention} has active Plex access. Trial started ({TRIAL_DAYS} days)."
                )
                logger.info("Trial started for %s (%s)", member.display_name, email)
            else:
                logger.info("Member %s already has Trial or Payer role.", member.display_name)
        else:
            logger.info("%s not yet shared on Plex server %s", email, server_name)

    except Exception as e:
        logger.error("Plex invite acceptance check failed for %s: %s", email, e)

__all__ = ["client", "bot", "TOKEN", "LIFETIME_ROLE"]
