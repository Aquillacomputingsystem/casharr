# bot/discord_adapter.py
import asyncio
import configparser, os, requests
from loghelper import logger

# Optional import: only if bot is running
try:
    from bot import bot
    import discord
except Exception:
    bot = None
    discord = None

CONFIG_PATH = os.path.join("config", "config.ini")
config = configparser.ConfigParser()
config.read(CONFIG_PATH, encoding="utf-8")

ENABLED = config.getboolean("Discord", "Enabled", fallback=False)
ADMIN_WEBHOOK = config.get("Discord", "AdminWebhookURL", fallback="").strip()

# ───────────────────────────────
# Safe wrappers
# ───────────────────────────────
def is_enabled() -> bool:
    return ENABLED and bot is not None

def send_admin(msg: str):
    """Send admin message via webhook if configured."""
    if not ADMIN_WEBHOOK:
        return
    try:
        requests.post(ADMIN_WEBHOOK, json={"content": msg})
    except Exception as e:
        logger.error(f"⚠️ Admin webhook failed: {e}")

async def _update_role_async(member, role_name: str):
    role = discord.utils.get(member.guild.roles, name=role_name)
    if not role:
        return
    await member.add_roles(role)
    logger.info(f"✅ Added role {role_name} to {member.display_name}")

def apply_role(discord_id: int, role_name: str):
    """Sync a member’s role in Discord if bot is running."""
    if not is_enabled():
        return
    try:
        member = None
        for g in bot.guilds:
            member = g.get_member(int(discord_id))
            if member:
                break
        if member:
            asyncio.run_coroutine_threadsafe(_update_role_async(member, role_name), bot.loop)
    except Exception as e:
        logger.error(f"⚠️ Failed to apply Discord role: {e}")

def dm(discord_id: int, message: str):
    """Send a DM safely."""
    if not is_enabled():
        return
    try:
        async def _dm():
            for g in bot.guilds:
                member = g.get_member(int(discord_id))
                if member:
                    try:
                        await member.send(message)
                        logger.info(f"✉️ DM sent to {member.display_name}")
                    except Exception as err:
                        logger.warning(f"⚠️ Couldn’t DM {member}: {err}")
                    break
        asyncio.run_coroutine_threadsafe(_dm(), bot.loop)
    except Exception as e:
        logger.error(f"⚠️ DM send failed: {e}")
