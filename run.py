# run.py — stable combined launcher (resilient)
import threading
import sys
from loghelper import logger
from ipnserver import app  # unified Flask (IPN + WebUI)

# ─────────────────────────────
# Start Flask / WebUI + IPN
# ─────────────────────────────
def start_flask():
    """Start unified Casharr Flask server (WebUI + IPN)."""
    try:
        logger.info("🌐 Starting Casharr WebUI + IPN on http://0.0.0.0:5000")
        app.run(host="0.0.0.0", port=5000, debug=False, use_reloader=False)
    except Exception as e:
        logger.error(f"⚠️ Flask WebUI/IPN failed to start: {e}")

# Run Flask in background
threading.Thread(target=start_flask, daemon=True, name="FlaskThread").start()

# ─────────────────────────────
# Discord bot — safe startup
# ─────────────────────────────
try:
    from bot import client, TOKEN
    # ✅ Force-load all bot modules (commands, events, tasks)
    import bot.events
    import bot.commands.user_commands
    import bot.commands.admin_commands
    import bot.commands.reports
    import bot.tasks.enforce_access
    import bot.tasks.audit_plex
    import bot.tasks.reminders

    logger.info("🤖 Launching Casharr Discord bot...")
    client.run(TOKEN)

except Exception as e:
    logger.error(f"⚠️ Discord failed to start: {e}")
    logger.warning("🔸 Running in WebUI + IPN-only mode (Discord unavailable).")

    # Keep alive so Flask/IPN continue running even if Discord fails
    try:
        while True:
            pass
    except KeyboardInterrupt:
        logger.info("🛑 Casharr stopped manually.")
        sys.exit(0)
