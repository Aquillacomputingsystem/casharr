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
    """Fully replace a user's access role in Discord."""
    if not is_enabled():
        return

    try:
        member = None
        for g in bot.guilds:
            member = g.get_member(int(discord_id))
            if member:
                break

        if not member:
            return

        async def _update():
            # Load config role names
            cfg = configparser.ConfigParser()
            cfg.read(CONFIG_PATH, encoding="utf-8")

            role_initial  = cfg.get("Discord", "InitialRole",  fallback="No Access").strip()
            role_trial    = cfg.get("Discord", "TrialRole",    fallback="Trial").strip()
            role_payer    = cfg.get("Discord", "PayerRole",    fallback="Payer").strip()
            role_lifetime = cfg.get("Discord", "LifetimeRole", fallback="Patreon").strip()

            # All roles that Casharr controls
            all_access_roles = [role_initial, role_trial, role_payer, role_lifetime]

            # Convert names → actual Discord role objects
            roles_to_remove = [
                discord.utils.get(member.guild.roles, name=r)
                for r in all_access_roles
            ]
            roles_to_remove = [r for r in roles_to_remove if r and r in member.roles]

            # Remove old roles
            if roles_to_remove:
                await member.remove_roles(*roles_to_remove, reason="Casharr status update")

            # Add new role
            new_role = discord.utils.get(member.guild.roles, name=role_name)
            if new_role:
                await member.add_roles(new_role, reason="Casharr status update")
                logger.info(f"🔄 Updated Discord role → {role_name} for {member.display_name}")
            else:
                logger.warning(f"⚠️ Role '{role_name}' not found in Discord.")

        asyncio.run_coroutine_threadsafe(_update(), bot.loop)

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
