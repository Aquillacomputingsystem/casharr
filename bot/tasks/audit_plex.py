# bot/tasks/audit_plex.py
import asyncio
from discord.ext import tasks
import discord
from configparser import ConfigParser
from loghelper import logger
from bot import (
    bot, plex, get_all_members,
    TRIAL_ROLE, PAYER_ROLE, INITIAL_ROLE, LIFETIME_ROLE,
    start_trial, end_trial, send_admin, parse_iso, TRIAL_DAYS
)

# ✅ Added: Task registry imports
from .task_registry import register_task, mark_start, mark_finish

# ─────────────────────────────
# Load Config
# ─────────────────────────────
CONFIG_PATH = "config/config.ini"
config = ConfigParser()
config.read(CONFIG_PATH, encoding="utf-8")
ACCESS_MODE = config.get("AccessMode", "Mode", fallback="Auto").strip().lower()


@tasks.loop(minutes=10)
async def audit_plex_access():
    """
    Runs every 10 minutes to verify Plex and Discord alignment.
    - Auto mode: upgrades and downgrades both occur automatically.
    - Manual mode: only upgrades occur automatically; downgrades are deferred to enforce_access.
    - Plex-only users (no Discord record) are skipped entirely.
    """
    # ✅ Added tracking start
    name = "Audit Plex Access"
    started = asyncio.get_event_loop().time()
    mark_start(name, audit_plex_access)

    logger.info("🔁 Running Plex access audit (%s mode)...", ACCESS_MODE.upper())

    try:
        server_name = plex.plex.friendlyName
        plex_users = {u.email.lower(): u for u in plex.account.users() if u.email}
        logger.info("📡 Retrieved %d Plex users from server '%s'", len(plex_users), server_name)
    except Exception as e:
        logger.error("⚠️ Could not fetch Plex user list: %s", e)
        # ✅ Added tracking finish (error exit)
        mark_finish(name, started, audit_plex_access)
        return

    normalized_server_name = server_name.lower().replace(" ", "").replace("-", "")

    # ─────────────────────────────
    # Iterate through all guilds and DB members
    # ─────────────────────────────
    for g in bot.guilds:
        logger.info("🔍 Auditing Plex access for guild: %s", g.name)
        lifetime_role = discord.utils.get(g.roles, name=LIFETIME_ROLE)
        trial_role = discord.utils.get(g.roles, name=TRIAL_ROLE)
        payer_role = discord.utils.get(g.roles, name=PAYER_ROLE)
        no_access_role = discord.utils.get(g.roles, name=INITIAL_ROLE)

        for row in get_all_members():
            try:
                discord_id = row[0]
                email = row[4] if len(row) > 4 else None
                if not email:
                    continue

                member = g.get_member(int(discord_id))
                if not member:
                    logger.debug("Skipping Plex-only user: %s (not in Discord)", email)
                    continue  # ✅ Plex-only users never touched

                # Skip lifetime members
                if lifetime_role and lifetime_role in member.roles:
                    logger.debug("🔒 Skipping Lifetime member %s", member.display_name)
                    continue

                # Check Plex access
                has_access = False
                plex_user = plex_users.get(email.lower())
                if plex_user:
                    for s in getattr(plex_user, "servers", []):
                        s_str = str(s).lower().replace(" ", "").replace("-", "")
                        s_name = getattr(s, "name", "").lower().replace(" ", "").replace("-", "")
                        if normalized_server_name in s_str or normalized_server_name in s_name:
                            has_access = True
                            break

                logger.debug(
                    "👤 Checking %s (%s): has_access=%s | Roles=%s",
                    member.display_name, email, has_access,
                    [r.name for r in member.roles]
                )

                # ─────────────────────────────
                # 1️⃣ Member gained Plex access → Upgrade
                # ─────────────────────────────
                if has_access and no_access_role in member.roles and payer_role not in member.roles:
                    logger.info("🎉 %s gained Plex access — upgrading to Trial", member.display_name)
                    await member.remove_roles(no_access_role)
                    if trial_role:
                        await member.add_roles(trial_role)
                        logger.info("✅ Added role '%s' to %s", TRIAL_ROLE, member.display_name)
                    start_trial(member.id, TRIAL_DAYS)
                    await send_admin(
                        f"🎉 {member.mention} gained Plex access. Trial started for {TRIAL_DAYS} days."
                    )
                    continue

                # ─────────────────────────────
                # 2️⃣ Member lost Plex access → Downgrade
                # ─────────────────────────────
                if not has_access and trial_role in member.roles and payer_role not in member.roles:
                    if ACCESS_MODE == "manual":
                        logger.info(
                            "⚠️ %s lost Plex access — manual mode active, deferring downgrade",
                            member.display_name,
                        )
                        await send_admin(
                            f"⚠️ {member.mention} lost Plex access — awaiting admin confirmation "
                            f"(Manual mode, no automatic removal)."
                        )
                        continue

                    # Auto mode only
                    logger.warning("⚠️ %s lost Plex access — reverting to INITIAL role", member.display_name)
                    await member.remove_roles(trial_role)
                    if no_access_role:
                        await member.add_roles(no_access_role)
                        logger.info("✅ Added role '%s' to %s", INITIAL_ROLE, member.display_name)

                    try:
                        plex.remove_user(email)
                    except Exception as e:
                        logger.warning("Could not remove Plex user %s: %s", email, e)

                    end_trial(member.id)
                    await send_admin(f"⚠️ {member.mention} lost Plex access. Reverted to {INITIAL_ROLE}.")
                    continue

                # ─────────────────────────────
                # 3️⃣ No change
                # ─────────────────────────────
                logger.debug("No change for %s (has_access=%s)", member.display_name, has_access)

            except Exception as e:
                logger.error("⚠️ Audit failed for a member: %s", e)

    logger.info("✅ Plex access audit completed.")

    # ✅ Added tracking finish
    mark_finish(name, started, audit_plex_access)


@audit_plex_access.before_loop
async def before_audit():
    await bot.wait_until_ready()
    logger.info("⏳ Waiting for bot ready before starting audit...")
    await asyncio.sleep(5)
    logger.info("⚡ Running first Plex access audit immediately...")
    try:
        await audit_plex_access()
    except Exception as e:
        logger.error("⚠️ Immediate audit failed: %s", e)

# ✅ Added: register this task for dashboard tracking
def _register():
    register_task("Audit Plex Access", audit_plex_access, "Every 10 minutes", audit_plex_access)
_register()
