
# webui/scheduler.py
import threading, time, traceback, shutil, os
from datetime import datetime, timedelta, timezone
from loghelper import logger
from database import (
    get_trial_members,
    get_payer_members,
    update_member_role,
    update_member_status,
    DB_PATH
)
from helpers.emailer import send_email
from helpers.sms import send_sms

def send_notification(email=None, subject=None, message=None):
    """Simplified notification using email + SMS"""
    if email:
        try: send_email(subject or "Casharr Notice", message, to=email)
        except Exception as e: logger.error(f"Email send failed: {e}")
    # Optional SMS broadcast
    try: send_sms(os.getenv("ADMIN_PHONE", ""), message)
    except Exception: pass


def backup_database_daily():
    """Daily DB backup to /exports"""
    ts = datetime.now().strftime("%Y.%m.%d_%H.%M.%S")
    out_dir = "exports"
    os.makedirs(out_dir, exist_ok=True)
    dest = os.path.join(out_dir, f"auto_backup_{ts}.db")
    try:
        shutil.copy2(DB_PATH, dest)
        logger.info(f"💾 Auto-backup completed → {dest}")
    except Exception as e:
        logger.error(f"⚠️ Auto-backup failed: {e}")


class Scheduler:
    def __init__(self):
        self.running = True
        self.tasks = []
        self.thread = threading.Thread(target=self._loop, daemon=True)
        self.thread.start()

    def add_task(self, name, interval, func):
        """Register a recurring task"""
        self.tasks.append({
            "name": name,
            "interval": interval,
            "func": func,
            "next": datetime.now(timezone.utc) + interval,
            "last_run": None,
        })
        logger.info(f"🕑 Registered scheduled task '{name}' every {interval}.")

    def _loop(self):
        while self.running:
            now = datetime.now(timezone.utc)
            for t in self.tasks:
                if now >= t["next"]:
                    logger.info(f"▶️ Running task: {t['name']}")
                    try:
                        t["func"]()
                        t["last_run"] = now
                    except Exception as e:
                        logger.error(f"⚠️ Task {t['name']} failed: {e}")
                        traceback.print_exc()
                    t["next"] = now + t["interval"]
            time.sleep(30)

    def stop(self):
        self.running = False


# ───────────────────────────────
# Example Tasks (App-Controlled)
# ───────────────────────────────
def enforce_access():
    """Run enforcement logic every 30 min."""
    now = datetime.now(timezone.utc)
    trials = get_trial_members()
    payers = get_payer_members()

    for discord_id, email, trial_end in trials:
        try:
            end = datetime.fromisoformat(trial_end)
            if end < now:
                update_member_role(discord_id, "No Access")
                send_notification(email=email,
                    subject="Trial Expired",
                    message="Your trial access has ended.")
        except Exception as e:
            logger.error(f"Error enforcing trial expiry for {email}: {e}")

    for discord_id, email, paid_until in payers:
        try:
            if paid_until and datetime.fromisoformat(paid_until) < now:
                update_member_role(discord_id, "No Access")
                send_notification(email=email,
                    subject="Subscription Expired",
                    message="Your payment period has ended.")
        except Exception as e:
            logger.error(f"Error enforcing paid expiry for {email}: {e}")

def daily_backup():
    """Create a DB backup daily at 4 AM."""
    backup_database_daily()

def send_expiry_reminders():
    """Notify members whose trial or payment expires soon (calendar-day based)."""
    import configparser, sqlite3

    cfg = configparser.ConfigParser()
    cfg.read(os.path.join("config", "config.ini"), encoding="utf-8")
    if not cfg.getboolean("Reminders", "Enabled", fallback=False):
        return

    days_before = int(cfg.get("Reminders", "DaysBeforeExpiry", fallback="1"))
    notify_email = cfg.getboolean("Reminders", "NotifyEmail", fallback=False)
    notify_sms = cfg.getboolean("Reminders", "NotifySMS", fallback=False)
    notify_discord = cfg.getboolean("Reminders", "NotifyDiscord", fallback=False)

    now = datetime.now(timezone.utc)
    today = now.date()

    # Calculate the calendar date the reminder should be sent on
    # Example: expiry_date = 2025-11-20, days_before=1 → reminder_date = 2025-11-19
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT discord_id, email, mobile, trial_end, paid_until FROM members")
    members = c.fetchall()
    conn.close()

    for discord_id, email, mobile, trial_end, paid_until in members:
        expires_on = None

        # ----- Trial expiry -----
        if trial_end:
            try:
                dt = datetime.fromisoformat(trial_end)
                expiry_date = dt.date()
                reminder_date = expiry_date - timedelta(days=days_before)

                # Send ONLY on the reminder calendar day, not “within next 24h”
                if today == reminder_date and dt > now:
                    expires_on = dt
            except Exception:
                pass

        # ----- Paid expiry -----
        if not expires_on and paid_until:
            try:
                dt = datetime.fromisoformat(paid_until)
                expiry_date = dt.date()
                reminder_date = expiry_date - timedelta(days=days_before)

                if today == reminder_date and dt > now:
                    expires_on = dt
            except Exception:
                pass

        if not expires_on:
            continue

        # ----- Send notifications -----
        subject = "⏰ Casharr Access Expiring Soon"
        body = f"Your access will expire on {expires_on.date()}.\n\nTo keep access, renew your plan."

        if notify_email and email:
            send_email(subject, body, to=email)
        if notify_sms and mobile:
            send_sms(mobile, f"Casharr reminder: expires {expires_on.date()}")
        if notify_discord and discord_id:
            from bot.discord_adapter import dm
            dm(discord_id, f"Your Casharr access will expire on {expires_on.date()}. Please renew soon!")

        logger.info(f"🔔 Calendar-based reminder sent to {email or mobile} for expiry {expires_on.date()}")


# Instantiate scheduler on import
scheduler = Scheduler()
scheduler.add_task("Enforce Access", timedelta(minutes=30), enforce_access)
scheduler.add_task("Daily Backup", timedelta(hours=24), daily_backup)
scheduler.add_task("Expiry Reminders", timedelta(hours=24), send_expiry_reminders)
