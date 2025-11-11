# run.py — unified launcher for Casharr
import threading, time, configparser, os
from loghelper import logger
from ipnserver import app

# ───────────────────────────────
# Load configuration
# ───────────────────────────────
cfg = configparser.ConfigParser()
cfg.read(os.path.join("config", "config.ini"), encoding="utf-8")

discord_enabled = cfg.getboolean("Discord", "Enabled", fallback=True)
discord_token = cfg.get("Discord", "BotToken", fallback="").strip()

# ───────────────────────────────
# Start Flask WebUI + IPN
# ───────────────────────────────
def start_flask():
    try:
        logger.info("🌐 Starting Casharr WebUI + IPN on http://0.0.0.0:5000")
        app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
    except Exception as e:
        logger.error(f"⚠️ Flask WebUI/IPN failed to start: {e}")

threading.Thread(target=start_flask, daemon=True, name="FlaskThread").start()

# ───────────────────────────────
# Optional Discord Bot
# ───────────────────────────────
if discord_enabled and discord_token:
    try:
        from bot import client
        import bot.events
        import bot.commands.user_commands
        import bot.commands.admin_commands
        import bot.commands.reports
        import bot.tasks.enforce_access
        import bot.tasks.audit_plex
        import bot.tasks.reminders

        logger.info("🤖 Launching Casharr Discord bot...")
        try:
            client.run(discord_token)
        except Exception as login_error:
            logger.error(f"⚠️ Discord login failed: {login_error}")
            logger.warning("🔸 Continuing without Discord (WebUI + IPN active).")

    except Exception as import_error:
        logger.error(f"⚠️ Discord failed to start: {import_error}")
        logger.warning("🔸 Continuing without Discord (WebUI + IPN active).")

else:
    logger.info("🤖 Discord disabled or missing token — running WebUI/IPN only.")

# ───────────────────────────────
# Keep main thread alive
# ───────────────────────────────
try:
    while True:
        time.sleep(60)
except KeyboardInterrupt:
    logger.info("🛑 Shutting down Casharr...")