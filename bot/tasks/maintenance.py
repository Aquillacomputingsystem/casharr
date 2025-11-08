# bot/tasks/maintenance.py
import os, shutil
from datetime import datetime, timezone, time
from discord.ext import tasks
from loghelper import logger
from bot import bot, DB_PATH, EXPORTS_DIR
from .task_registry import register_task, mark_start, mark_finish

# ─────────────────────────────
# Daily Database Backup Task
# ─────────────────────────────
@tasks.loop(time=time(4, 0, 0))  # Runs daily at 04:00 server time
async def backup_database_daily():
    """
    Creates a daily timestamped backup of members.db in /exports.
    Also logs start/finish times to task registry for the dashboard.
    """
    name = "Database Backup"
    started = datetime.now(timezone.utc)
    mark_start(name, backup_database_daily)

    try:
        if not os.path.exists(DB_PATH):
            logger.warning("⚠️ Database file not found, skipping backup.")
            return

        os.makedirs(EXPORTS_DIR, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        dst = os.path.join(EXPORTS_DIR, f"members_backup_{timestamp}.db")
        shutil.copy2(DB_PATH, dst)
        logger.info(f"💾 Database backup completed → {dst}")

    except Exception as e:
        logger.error(f"⚠️ Database backup failed: {e}")

    finally:
        mark_finish(name, started, backup_database_daily)

# ─────────────────────────────
# Manual Run Helper (Run Now button)
# ─────────────────────────────
async def run_backup_once():
    """Run a one-time backup on demand (used by dashboard ▶ button)."""
    try:
        if not os.path.exists(DB_PATH):
            logger.warning("⚠️ Database not found for manual backup.")
            return

        os.makedirs(EXPORTS_DIR, exist_ok=True)
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        dst = os.path.join(EXPORTS_DIR, f"members_backup_{timestamp}.db")
        shutil.copy2(DB_PATH, dst)
        logger.info(f"💾 Manual database backup created → {dst}")
    except Exception as e:
        logger.error(f"⚠️ Manual database backup failed: {e}")

# ─────────────────────────────
# Register for dashboard tracking
# ─────────────────────────────
def register_tasks():
    register_task("Database Backup", backup_database_daily, "Daily @ 04:00", run_backup_once)
