# bot/events.py
import asyncio
import discord
import threading
import traceback
from ipnserver import app
from loghelper import logger
from bot import (
    bot, plex, WELCOME_MESSAGE, INITIAL_ROLE, TRIAL_DAYS,
    send_admin, save_member, start_trial, check_and_upgrade_after_invite,
    REMINDERS_ENABLED, config
)
from database import get_member, set_referrer


# ─────────────────────────────
# Cache of invites for referral tracking
# ─────────────────────────────
invite_cache: dict[int, list[discord.Invite]] = {}


@bot.event
async def on_ready():
    """Run startup routines once the bot is connected."""
    logger.info("✅ Logged in as %s", bot.user)




    # ─────────────────────────────
    # Start PayPal IPN Flask server automatically
    # ─────────────────────────────
    if not any(t.name == "IPNServerThread" for t in threading.enumerate()):
        def run_flask():
            try:
                port = int(config.get("PayPal", "IPNListenPort", fallback="5000"))
                logger.info(f"🚀 Starting PayPal IPN Flask server on port {port}...")
                app.run(host="0.0.0.0", port=port, debug=False, use_reloader=False)
            except Exception as e:
                logger.error("⚠️ Flask IPN server failed: %s", e)

        t = threading.Thread(target=run_flask, daemon=True, name="IPNServerThread")
        t.start()
        await send_admin("✅ PayPal IPN listener started automatically.")

    # ─────────────────────────────
    # Cache current invites for referral tracking
    # ─────────────────────────────
    for g in bot.guilds:
        try:
            invite_cache[g.id] = await g.invites()
            logger.info("📨 Cached invites for %s", g.name)
        except Exception as e:
            logger.warning("⚠️ Could not cache invites for %s: %s", g.name, e)

    # ─────────────────────────────
    # Sync slash commands (verbose debug)
    # ─────────────────────────────
    logger.info("⚙️ Starting slash command sync...")
    try:
        synced = await bot.tree.sync()
        logger.info("✅ Slash commands synced successfully: %d commands.", len(synced))
        for cmd in synced:
            logger.info(f"🔹 Synced: /{cmd.name}")
    except Exception as e:
        tb = "".join(traceback.format_exception(type(e), e, e.__traceback__))
        logger.error(f"❌ Slash command sync failed:\n{tb}")

 

    # ─────────────────────────────
    # Notify admin channel that bot is online
    # ─────────────────────────────
    try:
        await send_admin(f"✅ **{bot.user.name}** is online and connected.")
        logger.info("📢 Sent admin online notification.")
    except Exception as e:
        logger.error(f"⚠️ Failed to send admin notification: {e}")



@bot.event
async def on_member_join(member: discord.Member):
    """Automatic onboarding, referral detection, and trial start for new users."""
    if member.bot:
        return

    logger.info("👋 Member joined: %s (%s)", member.name, member.id)
    guild = member.guild

    # Assign initial role
    initial_role = discord.utils.get(guild.roles, name=INITIAL_ROLE)
    if initial_role:
        await member.add_roles(initial_role)
        logger.info("✅ Assigned initial role '%s' to %s", INITIAL_ROLE, member.name)

    # ─────────────────────────────
    # Detect referral invite usage
    # ─────────────────────────────
    referrer_id = None
    used_invite = None
    try:
        invites_before = invite_cache.get(guild.id, [])
        invites_after = await guild.invites()
        for inv in invites_before:
            after_inv = next((x for x in invites_after if x.code == inv.code), None)
            if after_inv and inv.uses < after_inv.uses:
                used_invite = inv
                break
        invite_cache[guild.id] = invites_after  # refresh cache

        if used_invite and used_invite.inviter:
            referrer_id = str(used_invite.inviter.id)
            await send_admin(f"🤝 {member.mention} joined using {used_invite.inviter.mention}'s referral invite.")
            set_referrer(member.id, referrer_id)
    except Exception as e:
        logger.error("⚠️ Referral invite check failed for %s: %s", member.name, e)

    # ─────────────────────────────
    # Skip trial for returning members
    # ─────────────────────────────
    existing = get_member(member.id)
    if existing:
        await send_admin(f"ℹ️ {member.mention} rejoined; existing DB record found. No new trial started.")
        return

    # ─────────────────────────────
    # Onboard user via DM (new members only)
    # ─────────────────────────────
    try:
        dm = await member.create_dm()
        await dm.send(WELCOME_MESSAGE.format(user=member.name))
        logger.info("💬 Sent welcome message to %s", member.name)

        questions = [
            "What is your **first name**?",
            "What is your **last name**?",
            "What is the **email you used for Plex**?",
            "What is your **mobile number**?"
        ]
        answers = []

        for q in questions:
            await dm.send(q)

            def check(m):
                return m.author == member and isinstance(m.channel, discord.DMChannel)

            msg = await bot.wait_for("message", check=check, timeout=300)
            answers.append(msg.content.strip())

        first, last, email, mobile = answers
        tag = f"{member.name}#{member.discriminator}" if member.discriminator else member.name

        save_member(member.id, first, last, email, mobile, discord_tag=tag)
        logger.info("💾 Saved new member info for %s (email: %s)", member.name, email)

        # Referral acknowledgment
        if referrer_id:
            await dm.send(
                "🎁 You joined via a referral invite! Your referrer will earn bonus days when you subscribe."
            )

        # Plex Invite + Trial Setup
        logger.info("📨 Inviting %s to Plex", email)
        try:
            plex.invite_user(email)
        except Exception as e:
            logger.warning("⚠️ Could not send Plex invite to %s: %s", email, e)

        await asyncio.sleep(5)
        await check_and_upgrade_after_invite(member, email)

        logger.info("🧪 Starting %d-day trial for %s", TRIAL_DAYS, member.name)
        start_trial(member.id, TRIAL_DAYS)

        await dm.send("✅ Your details are saved and a Plex invite has been sent.")
        await send_admin(f"🧪 Trial started for {member.mention} ({email}).")

    except asyncio.TimeoutError:
        logger.warning("⏳ %s did not answer onboarding questions in time.", member.name)
        await send_admin(f"⚠️ {member.mention} did not complete onboarding questions.")
    except Exception as e:
        logger.error("⚠️ Onboarding failed for %s: %s", member.name, e)
        await send_admin(f"⚠️ Onboarding failed for {member.mention}: {type(e).__name__}: {e}")
try:
    from bot.commands.admin_commands import load_pending, _collect_member_details
except Exception:
    pass  # prevent duplicate command registration

@bot.event
async def on_message(message: discord.Message):
    """Handle late replies for persistent /request_details sessions."""
    if message.author.bot or not isinstance(message.channel, discord.DMChannel):
        return

    pending = load_pending()
    user_id = str(message.author.id)
    if user_id in pending:
        stage = pending[user_id]
        await _collect_member_details(message.author, resume_stage=stage)
