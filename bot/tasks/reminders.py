# casharr/bot/tasks/reminders.py
from datetime import datetime, timezone, timedelta
from discord.ext import tasks
import discord
import os
import configparser
from helpers.emailer import send_email
from helpers.sms import send_sms
from bot import (
    bot, get_all_for_reminders, parse_iso, TRIAL_REMINDER_MSG, PAID_REMINDER_MSG,
    pay_page, mark_trial_reminder_sent, mark_paid_reminder_sent, send_admin,
    REMINDER_DAYS, LIFETIME_ROLE
)
from .task_registry import register_task, mark_start, mark_finish


@tasks.loop(hours=12)
async def send_renewal_reminders():
    """Send trial and paid renewal reminders via Discord, Email, or SMS."""
    name = "Send Renewal Reminders"
    started = datetime.now(timezone.utc)
    mark_start(name, send_renewal_reminders)

    # Load reminder configuration
    cfg = configparser.ConfigParser()
    cfg.read(os.path.join("config", "config.ini"), encoding="utf-8")
    notify_discord = cfg.getboolean("Reminders", "NotifyDiscord", fallback=True)
    notify_email = cfg.getboolean("Reminders", "NotifyEmail", fallback=True)
    notify_sms = cfg.getboolean("Reminders", "NotifySMS", fallback=False)

    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=REMINDER_DAYS)
    due = get_all_for_reminders()

    for discord_id, email, mobile, trial_end, paid_until, trial_rem_at, paid_rem_at in due:
        # Find Discord member
        member = None
        for g in bot.guilds:
            m = g.get_member(int(discord_id))
            if m:
                member = m
                break
        if not member:
            continue

        # Skip lifetime members
        lifetime_role = None
        for g in bot.guilds:
            lifetime_role = discord.utils.get(g.roles, name=LIFETIME_ROLE)
            if lifetime_role:
                break
        if member and lifetime_role and lifetime_role in member.roles:
            continue

        # ────────────────────────────────
        # TRIAL REMINDER
        # ────────────────────────────────
        t_end = parse_iso(trial_end)
        if t_end and now <= t_end <= horizon and not trial_rem_at:
            msg = TRIAL_REMINDER_MSG.format(
                date=t_end.strftime("%Y-%m-%d"),
                m1=pay_page(discord_id, "1"),
                m3=pay_page(discord_id, "3"),
                m6=pay_page(discord_id, "6"),
                m12=pay_page(discord_id, "12")
            )

            sent_channels = []

            # Discord
            if notify_discord and member:
                try:
                    dm = await member.create_dm()
                    await dm.send(msg)
                    sent_channels.append("Discord")
                except Exception as e:
                    print(f"⚠️ Discord DM (trial) failed for {discord_id}: {e}")

            # Email
            if notify_email and email:
                try:
                    send_email("Casharr Trial Reminder", msg, to=email)
                    sent_channels.append("Email")
                except Exception as e:
                    print(f"⚠️ Email (trial) failed for {email}: {e}")

            # SMS
            if notify_sms and mobile:
                try:
                    send_sms(mobile, msg)
                    sent_channels.append("SMS")
                except Exception as e:
                    print(f"⚠️ SMS (trial) failed for {mobile}: {e}")

            if sent_channels:
                mark_trial_reminder_sent(discord_id)
                await send_admin(
                    f"🔔 Trial reminder sent to {member.mention if member else email or discord_id} "
                    f"(ends {t_end.date()}) via {', '.join(sent_channels)}."
                )

        # ────────────────────────────────
        # PAID REMINDER
        # ────────────────────────────────
        p_end = parse_iso(paid_until)
        if p_end and now <= p_end <= horizon and not paid_rem_at:
            msg = PAID_REMINDER_MSG.format(
                date=p_end.strftime("%Y-%m-%d"),
                m1=pay_page(discord_id, "1"),
                m3=pay_page(discord_id, "3"),
                m6=pay_page(discord_id, "6"),
                m12=pay_page(discord_id, "12")
            )

            sent_channels = []

            # Discord
            if notify_discord and member:
                try:
                    dm = await member.create_dm()
                    await dm.send(msg)
                    sent_channels.append("Discord")
                except Exception as e:
                    print(f"⚠️ Discord DM (paid) failed for {discord_id}: {e}")

            # Email
            if notify_email and email:
                try:
                    send_email("Casharr Subscription Reminder", msg, to=email)
                    sent_channels.append("Email")
                except Exception as e:
                    print(f"⚠️ Email (paid) failed for {email}: {e}")

            # SMS
            if notify_sms and mobile:
                try:
                    send_sms(mobile, msg)
                    sent_channels.append("SMS")
                except Exception as e:
                    print(f"⚠️ SMS (paid) failed for {mobile}: {e}")

            if sent_channels:
                mark_paid_reminder_sent(discord_id)
                await send_admin(
                    f"🔔 Subscription reminder sent to {member.mention if member else email or discord_id} "
                    f"(ends {p_end.date()}) via {', '.join(sent_channels)}."
                )

    # ✅ Finish task
    mark_finish(name, started, send_renewal_reminders)


def _register():
    """Register this task in the dashboard."""
    register_task("Send Renewal Reminders", send_renewal_reminders, "Every 12 hours", send_renewal_reminders)

_register()
