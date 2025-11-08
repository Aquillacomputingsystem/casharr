# casharr/bot/tasks/reminders.py
from datetime import datetime, timezone, timedelta
from discord.ext import tasks
import discord  # ✅ Added this line
from bot import (
    bot, get_all_for_reminders, parse_iso, TRIAL_REMINDER_MSG, PAID_REMINDER_MSG,
    pay_page, mark_trial_reminder_sent, mark_paid_reminder_sent, send_admin,
    REMINDER_DAYS, LIFETIME_ROLE
)

# ✅ Added: Task Registry support
from .task_registry import register_task, mark_start, mark_finish

@tasks.loop(hours=12)
async def send_renewal_reminders():
    # ✅ Tracking start
    name = "Send Renewal Reminders"
    started = datetime.now(timezone.utc)
    mark_start(name, send_renewal_reminders)

    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=REMINDER_DAYS)
    due = get_all_for_reminders()

    for discord_id, email, trial_end, paid_until, trial_rem_at, paid_rem_at in due:
        # Find member across all guilds
        member = None
        for g in bot.guilds:
            m = g.get_member(int(discord_id))
            if m:
                member = m
                break
        if not member:
            continue

        # ✅ Skip Lifetime members entirely
        lifetime_role = None
        for g in bot.guilds:
            lifetime_role = discord.utils.get(g.roles, name=LIFETIME_ROLE)
            if lifetime_role:
                break
        if lifetime_role and lifetime_role in member.roles:
            # No reminders for lifetime members
            continue

        # ────────────────────────────────
        # Trial reminder
        # ────────────────────────────────
        t_end = parse_iso(trial_end)
        if t_end and now <= t_end <= horizon and not trial_rem_at:
            try:
                dm = await member.create_dm()
                msg = TRIAL_REMINDER_MSG.format(
                    date=t_end.strftime("%Y-%m-%d"),
                    m1=pay_page(discord_id, "1"),
                    m3=pay_page(discord_id, "3"),
                    m6=pay_page(discord_id, "6"),
                    m12=pay_page(discord_id, "12")
                )
                await dm.send(msg)
                mark_trial_reminder_sent(discord_id)
                await send_admin(f"🔔 Trial reminder sent to {member.mention} (ends {t_end.date()}).")
            except Exception as e:
                print(f"⚠️ DM trial reminder failed for {discord_id}: {e}")

        # ────────────────────────────────
        # Paid reminder
        # ────────────────────────────────
        p_end = parse_iso(paid_until)
        if p_end and now <= p_end <= horizon and not paid_rem_at:
            try:
                dm = await member.create_dm()
                msg = PAID_REMINDER_MSG.format(
                    date=p_end.strftime("%Y-%m-%d"),
                    m1=pay_page(discord_id, "1"),
                    m3=pay_page(discord_id, "3"),
                    m6=pay_page(discord_id, "6"),
                    m12=pay_page(discord_id, "12")
                )
                await dm.send(msg)
                mark_paid_reminder_sent(discord_id)
                await send_admin(f"🔔 Subscription reminder sent to {member.mention} (ends {p_end.date()}).")
            except Exception as e:
                print(f"⚠️ DM paid reminder failed for {discord_id}: {e}")

    # ✅ Tracking finish
    mark_finish(name, started, send_renewal_reminders)


# ✅ Added: Dashboard registration (non-destructive)
def _register():
    register_task("Send Renewal Reminders", send_renewal_reminders, "Every 12 hours", send_renewal_reminders)
_register()
