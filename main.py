# main.py
import threading, time, configparser, os
from loghelper import logger
from ipnserver import app  # unified Flask app with WebUI + IPN

# ───────────────────────────────
# Read Discord enable flag
# ───────────────────────────────
cfg = configparser.ConfigParser()
cfg.read(os.path.join("config", "config.ini"), encoding="utf-8")
discord_enabled = cfg.getboolean("Discord", "Enabled", fallback=True)

def start_discord():
    """Run the Discord bot safely in its own thread."""
    if not discord_enabled:
        logger.info("🤖 Discord disabled in config. Skipping bot startup.")
        return
    try:
        from bot import client, TOKEN
        import bot.events  # ensure events load
        logger.info("🚀 Starting Casharr Discord bot...")
        client.run(TOKEN)
    except Exception as e:
        logger.error(f"⚠️ Failed to start Discord bot: {type(e).__name__}: {e}")
        logger.warning("💡 Continuing with WebUI and IPN server active (Discord unavailable).")

def start_flask():
    """Run the unified Flask WebUI + IPN server."""
    logger.info("🌐 Starting Casharr WebUI + IPN server on http://localhost:5000")
    app.run(host="0.0.0.0", port=5000, use_reloader=False)

if __name__ == "__main__":
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    flask_thread.start()

    if discord_enabled:
        discord_thread = threading.Thread(target=start_discord, daemon=True)
        discord_thread.start()

    logger.info("✅ Casharr started successfully. Press Ctrl+C to stop.")

    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("🛑 Shutting down Casharr...")