# bot/tasks/enforce_access.py
from .task_registry import register_task, mark_start, mark_finish
from datetime import datetime, timezone, timedelta   # ✅ keep this line only
from discord.ext import tasks
import discord
import sqlite3, os, asyncio, json
from configparser import ConfigParser
from loghelper import logger
from bot import (
    bot, plex, parse_iso, get_trial_members, get_payer_members,
    TRIAL_ROLE, INITIAL_ROLE, PAYER_ROLE, LIFETIME_ROLE, send_admin, end_trial
)
from database import DB_PATH

# ─────────────────────────────
# Load Config
# ─────────────────────────────
CONFIG_PATH = os.path.join("config", "config.ini")
config = ConfigParser()
config.read(CONFIG_PATH, encoding="utf-8")
ACCESS_MODE = config.get("AccessMode", "Mode", fallback="Auto").strip().lower()

# Skip file to track deferrals
SKIP_FILE = os.path.join("data", "skip_deferrals.json")
os.makedirs("data", exist_ok=True)
if not os.path.exists(SKIP_FILE):
    with open(SKIP_FILE, "w") as f:
        json.dump({}, f)

def load_skips():
    try:
        with open(SKIP_FILE, "r") as f:
            return json.load(f)
    except Exception:
        return {}

def save_skips(data):
    with open(SKIP_FILE, "w") as f:
        json.dump(data, f, indent=2)

# ─────────────────────────────
# Sync Helper
# ─────────────────────────────
def sync_trial_durations():
    CONFIG_PATH = os.path.join("config", "config.ini")
    config = ConfigParser()
    config.read(CONFIG_PATH)

    try:
        new_duration = int(config["Trial"].get("DurationDays", 30))
    except Exception:
        new_duration = 30

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT discord_id, trial_start, trial_end FROM members WHERE trial_end IS NOT NULL")
    rows = c.fetchall()

    updated = 0
    expired_now = []  # Track users whose trial just became expired

    for discord_id, trial_start, trial_end in rows:
        if not trial_start or not trial_end:
            continue
        try:
            start = datetime.fromisoformat(trial_start)
            end = datetime.fromisoformat(trial_end)
            expected_end = start + timedelta(days=new_duration)
            if abs((expected_end - end).days) >= 1:
                c.execute(
                    "UPDATE members SET trial_end=? WHERE discord_id=?",
                    (expected_end.isoformat(), str(discord_id)),
                )
                updated += 1
                if expected_end < datetime.now(timezone.utc):
                    expired_now.append(str(discord_id))
        except Exception:
            continue

    conn.commit()
    conn.close()

    # ─────────────────────────────
    # 🔔 Trigger manual enforcement if any expired after sync
    # ─────────────────────────────
    if updated > 0 and ACCESS_MODE == "manual" and expired_now:
        async def notify_manual_check():
            await send_admin(
                f"🕒 {updated} trial durations synced to new {new_duration}-day length.\n"
                f"⚠️ {len(expired_now)} member(s) now past expiry — check your DMs for removal confirmations."
            )
            # Run enforcement immediately
            await enforce_access()
        asyncio.create_task(notify_manual_check())

    return updated

# ─────────────────────────────
# Helper: DM admin for confirmation
# ─────────────────────────────
async def ask_admin_confirmation(admin, member, email, reason, skip_data):
    """Ask admin via DM whether to remove access; respects skip deferral."""
    uid = str(member.id)
    now = datetime.now(timezone.utc)

    # Skip if within 7-day deferral
    if uid in skip_data:
        last_skip = datetime.fromisoformat(skip_data[uid])
        if now - last_skip < timedelta(days=7):
            logger.info("Skipping prompt for %s (within 7-day defer)", member.display_name)
            return False

    try:
        dm = await admin.create_dm()
        await dm.send(
            f"{reason}\n"
            f"Member: {member.mention} ({email})\n"
            f"Action: Downgrade → `{INITIAL_ROLE}`\n"
            f"Reply **yes** to confirm removal or **skip** to defer for 7 days."
        )

        def check(m):
            return (
                m.author == admin
                and isinstance(m.channel, discord.DMChannel)
                and m.content.lower() in ["yes", "skip"]
            )

        msg = await bot.wait_for("message", check=check, timeout=86400)  # 24h timeout
        choice = msg.content.lower()

        if choice == "yes":
            logger.info("Admin confirmed removal for %s", member.display_name)
            return True
        elif choice == "skip":
            skip_data[uid] = now.isoformat()
            save_skips(skip_data)
            await dm.send(f"⏸️ Skipped {member.display_name}. I’ll remind you again in 7 days.")
            return False
    except asyncio.TimeoutError:
        try:
            await dm.send(f"⏰ No response for {member.display_name}. Ignored for now.")
        except Exception:
            pass
        return False
    except Exception as e:
        logger.error("⚠️ DM confirmation failed for %s: %s", member.display_name, e)
        return False

# ─────────────────────────────
# Main Enforcement Loop
# ─────────────────────────────
@tasks.loop(minutes=30)
async def enforce_access():
    """
    Checks expired trials/payments and handles access depending on AccessMode.

    AUTO mode: downgrades and Plex removals happen automatically.
    MANUAL mode: upgrades happen automatically, but downgrades require admin DM approval.
    Plex-only users (not in Discord) are never touched.
    """
    # ─────────────────────────────
    # Start + Time Tracking
    # ─────────────────────────────
    name = "Enforce Access"
    started = datetime.now(timezone.utc)
    mark_start(name, enforce_access)

    # ✅ Define `now` once, early
    now = datetime.now(timezone.utc)

    skip_data = load_skips()
    logger.info("🔒 Enforcement cycle started (%s)", ACCESS_MODE.upper())

    for g in bot.guilds:
        admin_role = discord.utils.get(g.roles, name="Admin")
        admin = next((m for m in g.members if admin_role in m.roles), None)
        if not admin:
            logger.warning("⚠️ No admin found in guild %s — skipping enforcement.", g.name)
            continue

        lifetime_role = discord.utils.get(g.roles, name=LIFETIME_ROLE)

        # ────────── Trial Expiry ──────────
        for discord_id, email, trial_end in get_trial_members():
            try:
                end_time = parse_iso(trial_end)
                if not end_time or now <= end_time:
                    continue

                member = g.get_member(int(discord_id))
                if not member:
                    logger.info("Skipping Plex-only user (no Discord link): %s", email)
                    continue

                # Skip lifetime members
                if lifetime_role and lifetime_role in member.roles:
                    logger.info("⏳ Skipping lifetime member %s (trial expiry)", member.display_name)
                    continue

                trial_role = discord.utils.get(g.roles, name=TRIAL_ROLE)
                init_role = discord.utils.get(g.roles, name=INITIAL_ROLE)

                confirmed = True
                if ACCESS_MODE == "manual":
                    reason = f"⚠️ Trial expired for {member.display_name}."
                    confirmed = await ask_admin_confirmation(admin, member, email, reason, skip_data)

                if not confirmed:
                    continue

                # Downgrade confirmed or in auto mode
                if trial_role and trial_role in member.roles:
                    await member.remove_roles(trial_role)
                if init_role and init_role not in member.roles:
                    await member.add_roles(init_role)

                # Remove Plex only if linked user exists
                try:
                    if email:
                        plex.remove_user(email)
                except Exception as e:
                    logger.warning("Could not remove Plex access for %s: %s", email, e)

                end_trial(member.id)
                await send_admin(
                    f"⚠️ {member.mention}'s trial expired — reverted to {INITIAL_ROLE}."
                    + (" (Manual mode, confirmed)" if ACCESS_MODE == "manual" else "")
                )
                logger.info("Trial expired and downgraded %s (%s)", member.display_name, email)

            except Exception as e:
                logger.error("Error processing trial expiry for %s: %s", email, e)

        # ────────── Paid Expiry ──────────
        for discord_id, email, paid_until in get_payer_members():
            try:
                paid_time = parse_iso(paid_until)
                if not paid_time or now <= paid_time:
                    continue

                member = g.get_member(int(discord_id))
                if not member:
                    logger.info("Skipping Plex-only user (no Discord link): %s", email)
                    continue

                # Skip lifetime members
                if lifetime_role and lifetime_role in member.roles:
                    logger.info("⏳ Skipping lifetime member %s (paid expiry)", member.display_name)
                    continue

                payer_role = discord.utils.get(g.roles, name=PAYER_ROLE)
                init_role = discord.utils.get(g.roles, name=INITIAL_ROLE)

                confirmed = True
                if ACCESS_MODE == "manual":
                    reason = f"💸 Subscription expired for {member.display_name}."
                    confirmed = await ask_admin_confirmation(admin, member, email, reason, skip_data)

                if not confirmed:
                    continue

                # Downgrade confirmed or auto
                if payer_role and payer_role in member.roles:
                    await member.remove_roles(payer_role)
                if init_role and init_role not in member.roles:
                    await member.add_roles(init_role)

                # Remove Plex only if linked
                try:
                    if email:
                        plex.remove_user(email)
                except Exception as e:
                    logger.warning("Could not remove Plex access for %s: %s", email, e)

                await send_admin(
                    f"💸 {member.mention}'s subscription expired — reverted to {INITIAL_ROLE}."
                    + (" (Manual mode, confirmed)" if ACCESS_MODE == "manual" else "")
                )
                logger.info("Subscription expired and downgraded %s (%s)", member.display_name, email)

            except Exception as e:
                logger.error("Error processing payer expiry for %s: %s", email, e)

    logger.info("✅ Enforcement cycle completed.")

    # ✅ Added tracking finish
    mark_finish(name, started, enforce_access)


# ✅ Added: dashboard registration (non-destructive)
def _register():
    register_task("Enforce Access", enforce_access, "Every 30 minutes", enforce_access)

    async def _run_once():
        sync_trial_durations()
    register_task("Sync Trial Durations", type("Temp", (), {"next_iteration": None})(),
                  "On demand", _run_once)
_register()

# ─────────────────────────────
# Automatic Daily Backup Task
# ─────────────────────────────
from discord.ext import tasks
import shutil
from datetime import datetime

@tasks.loop(hours=24)
async def auto_backup():
    from database import DB_PATH
    os.makedirs("exports", exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")  # ✅ simplified call
    shutil.copy2(DB_PATH, f"exports/auto_backup_{stamp}.db")
    logger.info("💾 Automatic database backup created.")

@auto_backup.before_loop
async def before_backup():
    await bot.wait_until_ready()
    logger.info("⏳ Waiting for bot ready before starting auto backup...")

# ─────────────────────────────
# Register backup after bot ready
# ─────────────────────────────
async def start_auto_backup_once_ready():
    await bot.wait_until_ready()
    if not auto_backup.is_running():
        auto_backup.start()
        logger.info("💾 Auto backup loop started after bot ready.")

import asyncio
# ─────────────────────────────
# Register backup loop after bot ready
# ─────────────────────────────
async def start_auto_backup_once_ready():
    await bot.wait_until_ready()
    if not auto_backup.is_running():
        auto_backup.start()
        logger.info("💾 Auto backup loop started after bot ready.")
