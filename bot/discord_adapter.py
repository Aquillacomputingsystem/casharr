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

def _get_config_roles():
    """Return the 4 access role names from config.ini."""
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_PATH, encoding="utf-8")

    initial  = cfg.get("Discord", "InitialRole",  fallback="No Access").strip()
    trial    = cfg.get("Discord", "TrialRole",    fallback="Trial").strip()
    payer    = cfg.get("Discord", "PayerRole",    fallback="Payer").strip()
    lifetime = cfg.get("Discord", "LifetimeRole", fallback="Patreon").strip()

    return initial, trial, payer, lifetime


async def _update_role_async(member, role_name: str):
    """
    Remove any existing Casharr access roles and apply the given one
    (all driven from config.ini).
    """
    if not discord:
        return

    initial, trial, payer, lifetime = _get_config_roles()
    all_names = [initial, trial, payer, lifetime]

    # Build list of existing access roles to remove
    roles_to_remove = [
        discord.utils.get(member.guild.roles, name=rname)
        for rname in all_names
    ]
    roles_to_remove = [r for r in roles_to_remove if r and r in member.roles]

    # Remove old access roles
    if roles_to_remove:
        await member.remove_roles(*roles_to_remove, reason="Casharr status update")

    # Add new role
    new_role = discord.utils.get(member.guild.roles, name=role_name)
    if new_role:
        await member.add_roles(new_role, reason="Casharr status update")
        logger.info(f"✅ Updated Discord role → {role_name} for {member.display_name}")
    else:
        logger.warning(f"⚠️ Role '{role_name}' not found in Discord.")


def apply_role(discord_id: int, role_name: str):
    """Sync a member’s role in Discord if bot is running."""
    if not is_enabled() or not bot:
        return
    try:
        member = None
        for g in bot.guilds:
            member = g.get_member(int(discord_id))
            if member:
                break
        if member:
            asyncio.run_coroutine_threadsafe(
                _update_role_async(member, role_name),
                bot.loop
            )
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
