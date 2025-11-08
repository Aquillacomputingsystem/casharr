# main.py
import threading, time
from bot import client, TOKEN
from loghelper import logger
from ipnserver import app  # unified Flask app with WebUI + IPN
import bot.events  # make sure events load for the bot

def start_discord():
    """Run the Discord bot safely in its own thread."""
    try:
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
    # Start Flask in one thread and Discord in another
    flask_thread = threading.Thread(target=start_flask, daemon=True)
    discord_thread = threading.Thread(target=start_discord, daemon=True)

    flask_thread.start()
    discord_thread.start()

    logger.info("✅ Casharr started successfully. Press Ctrl+C to stop.")

    # Keep main process alive
    try:
        while True:
            time.sleep(60)
    except KeyboardInterrupt:
        logger.info("🛑 Shutting down Casharr...")
