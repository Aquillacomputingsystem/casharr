# loghelper.py
import sys, io, logging, os
from datetime import datetime

# ───────────────────────────────
# Force UTF-8 for all console output (Windows safe)
# ───────────────────────────────
try:
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")
except Exception:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ───────────────────────────────
# Logging configuration
# ───────────────────────────────
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)
# ─────────────────────────────
# Auto log retention cleanup
# ─────────────────────────────
import time, configparser
cfg_path = os.path.join("config", "config.ini")
cfg = configparser.ConfigParser()
cfg.read(cfg_path, encoding="utf-8")
retention = int(cfg.get("Logging", "RetentionDays", fallback="7"))
now = time.time()
for f in os.listdir(LOG_DIR):
    path = os.path.join(LOG_DIR, f)
    if os.path.isfile(path) and now - os.path.getmtime(path) > retention * 86400:
        os.remove(path)
        
# Generate a unique log filename each run
timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
LOG_FILE = os.path.join(LOG_DIR, f"{timestamp}.log")

def setup_logger():
    """Configure timestamped log file + console logger (UTF-8 safe)."""
    logger = logging.getLogger("casharr")
    logger.setLevel(logging.INFO)

    # Avoid duplicate handlers if module reloads
    if logger.handlers:
        return logger

    # Common log format
    log_format = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(message)s",
        "%Y-%m-%d %H:%M:%S"
    )

    # ───────────────────────────────
    # File handler (new file each restart)
    # ───────────────────────────────
    file_handler = logging.FileHandler(LOG_FILE, encoding="utf-8")
    file_handler.setFormatter(log_format)

    # ───────────────────────────────
    # Console handler (UTF-8 safe)
    # ───────────────────────────────
    console_stream = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    console_handler = logging.StreamHandler(console_stream)
    console_handler.setFormatter(log_format)

    # Attach both handlers
    logger.addHandler(file_handler)
    logger.addHandler(console_handler)

    # ───────────────────────────────
    # Write startup separator
    # ───────────────────────────────
    logger.info("──────────────────────────────────────────────")
    logger.info(f"🪄 New session started: {timestamp}")
    logger.info("──────────────────────────────────────────────")

    return logger

# Global logger instance
logger = setup_logger()

latest_link = os.path.join(LOG_DIR, "latest.log")
try:
    if os.path.exists(latest_link):
        os.remove(latest_link)
    os.symlink(os.path.basename(LOG_FILE), latest_link)
except Exception:
    with open(latest_link, "w", encoding="utf-8") as f:
        f.write(f"Redirect → {os.path.basename(LOG_FILE)}\n")
