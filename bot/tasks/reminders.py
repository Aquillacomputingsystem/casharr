# casharr/bot/tasks/reminders.py
from datetime import datetime, timezone, timedelta
from discord.ext import tasks
import discord
import os
import configparser
from helpers.emailer import send_email
from helpers.sms import send_sms
from bot import (
    bot,
    get_all_for_reminders,
    parse_iso,
    TRIAL_REMINDER_MSG,
    PAID_REMINDER_MSG,
    pay_page,
    mark_trial_reminder_sent,
    mark_paid_reminder_sent,
    send_admin,
    REMINDER_DAYS,
    LIFETIME_ROLE,
)
from .task_registry import register_task, mark_start, mark_finish


def send_notification(discord_member, email, mobile, subject, message, cfg):
    """Send reminder across all enabled channels and return list of channels that succeeded."""
    sent_channels = []
    notify_discord = cfg.getboolean("Reminders", "NotifyDiscord", fallback=True)
    notify_email = cfg.getboolean("Reminders", "NotifyEmail", fallback=True)
    notify_sms = cfg.getboolean("Reminders", "NotifySMS", fallback=False)

    # Discord
    if notify_discord and discord_member:
        try:
            import asyncio
            asyncio.run_coroutine_threadsafe(
                discord_member.send(message), bot.loop
            )
            sent_channels.append("Discord")
        except Exception as e:
            print(f"⚠️ Discord DM failed for {discord_member}: {e}")

    # Email
    if notify_email and email:
        try:
            send_email(subject, message, to=email)
            sent_channels.append("Email")
        except Exception as e:
            print(f"⚠️ Email send failed for {email}: {e}")

    # SMS
    if notify_sms and mobile:
        try:
            send_sms(mobile, message)
            sent_channels.append("SMS")
        except Exception as e:
            print(f"⚠️ SMS send failed for {mobile}: {e}")

    return sent_channels


@tasks.loop(hours=12)
async def send_renewal_reminders():
    """Send trial and paid renewal reminders via Discord, Email, or SMS."""
    task_name = "Send Renewal Reminders"
    started = datetime.now(timezone.utc)
    mark_start(task_name, send_renewal_reminders)

    cfg = configparser.ConfigParser()
    cfg.read(os.path.join("config", "config.ini"), encoding="utf-8")
    
    SERVER_NAME = cfg.get("General", "ServerName", fallback="My Plex Server")
    now = datetime.now(timezone.utc)
    horizon = now + timedelta(days=REMINDER_DAYS)
    due = get_all_for_reminders()

    # Find lifetime role once
    lifetime_role = None
    for g in bot.guilds:
        r = discord.utils.get(g.roles, name=LIFETIME_ROLE)
        if r:
            lifetime_role = r
            break

    for discord_id, email, mobile, trial_end, paid_until, trial_rem_at, paid_rem_at in due:
        # Skip lifetime members
        member = None
        if discord_id and discord_id.isdigit():
            for g in bot.guilds:
                m = g.get_member(int(discord_id))
                if m:
                    member = m
                    if lifetime_role and lifetime_role in m.roles:
                        member = None
                    break

        # ========== TRIAL REMINDER ==========
        t_end = parse_iso(trial_end)
        if t_end and now <= t_end <= horizon and not trial_rem_at:
            subject = f"{SERVER_NAME} Trial Reminder"
            msg = TRIAL_REMINDER_MSG.format(
                date=t_end.strftime("%Y-%m-%d"),
                m1=pay_page(discord_id, "1"),
                m3=pay_page(discord_id, "3"),
                m6=pay_page(discord_id, "6"),
                m12=pay_page(discord_id, "12"),
            )
            sent = send_notification(member, email, mobile, subject, msg, cfg)
            if sent:
                mark_trial_reminder_sent(discord_id or email or mobile)
                await send_admin(
                    f"🔔 Trial reminder sent to {member.mention if member else email or mobile} "
                    f"(ends {t_end.date()}) via {', '.join(sent)}."
                )

        # ========== PAID REMINDER ==========
        p_end = parse_iso(paid_until)
        if p_end and now <= p_end <= horizon and not paid_rem_at:
            subject = f"{SERVER_NAME} Subscription Renewal Reminder"
            msg = PAID_REMINDER_MSG.format(
                date=p_end.strftime("%Y-%m-%d"),
                m1=pay_page(discord_id, "1"),
                m3=pay_page(discord_id, "3"),
                m6=pay_page(discord_id, "6"),
                m12=pay_page(discord_id, "12"),
            )
            sent = send_notification(member, email, mobile, subject, msg, cfg)
            if sent:
                mark_paid_reminder_sent(discord_id or email or mobile)
                await send_admin(
                    f"🔔 Subscription reminder sent to {member.mention if member else email or mobile} "
                    f"(ends {p_end.date()}) via {', '.join(sent)}."
                )

    mark_finish(task_name, started, send_renewal_reminders)


def _register():
    register_task("Send Renewal Reminders", send_renewal_reminders, "Every 12 hours", send_renewal_reminders)


_register()
