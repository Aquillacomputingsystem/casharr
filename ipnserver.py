# ipnserver.py
from flask import Flask, request, redirect
import discord
import requests, os, configparser, asyncio, json, sqlite3
from datetime import datetime, timezone, timedelta
import psutil
import time
from bot import bot, plex
from webui.scheduler import scheduler  # ensures background loop starts

APP_START = time.time()


# ────────────────────────────────
# Database + WebUI imports
# ────────────────────────────────
from database import (
    update_payment,
    clear_trial_after_payment,
    get_member,
    mark_promo_used,
    has_used_promo,
    is_promo_eligible,
)
from webui.app import webui

# ────────────────────────────────
# Flask application
# ────────────────────────────────
app = Flask(__name__)
logger_msg = "🧠 WebUI Scheduler initialized (background tasks running)."
print(logger_msg)
app.register_blueprint(webui)   # ✅ register blueprint once
import os
app.secret_key = os.environ.get("CASHARR_SECRET", os.urandom(24))


# ────────────────────────────────
# Load configuration
# ────────────────────────────────
CONFIG_PATH = os.path.join("config", "config.ini")
config = configparser.ConfigParser()
config.read(CONFIG_PATH, encoding="utf-8")
# Discord enable flag
# ───────────────────────────────
DISCORD_ENABLED = config.getboolean("Discord", "Enabled", fallback=True)

DOMAIN = config["Site"].get("Domain", "").rstrip("/")
PAYPAL_MODE = config["PayPal"].get("Mode", "live").lower()
BUSINESS_EMAIL = config["PayPal"]["BusinessEmail"]
ADMIN_WEBHOOK_URL = config["Discord"].get("AdminWebhookURL", "").strip()

PAYPAL_VERIFY = (
    "https://ipnpb.paypal.com/cgi-bin/webscr"
    if PAYPAL_MODE == "live"
    else "https://ipnpb.sandbox.paypal.com/cgi-bin/webscr"
)
CURRENCY = config["Pricing"].get("DefaultCurrency", "AUD")

# ────────────────────────────────
# ⚙️ TEST MODE CONTROL
# ────────────────────────────────
TEST_MODE = PAYPAL_MODE != "live"
print(f"🧩 IPN server started — MODE: {PAYPAL_MODE.upper()}, TEST_MODE: {TEST_MODE}")

# ────────────────────────────────
# Log incoming IPN payloads
# ────────────────────────────────
LOG_DIR = "logs"
os.makedirs(LOG_DIR, exist_ok=True)
LOG_FILE = os.path.join(LOG_DIR, "ipn_debug.log")

def log_ipn(data, verified):
    entry = {
        "timestamp": datetime.utcnow().isoformat(),
        "verified": verified,
        "data": data,
    }
    try:
        with open(LOG_FILE, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception as e:
        print(f"⚠️ Could not write IPN log: {e}")

# ────────────────────────────────
# PayPal IPN Endpoint
# ────────────────────────────────
@app.route("/paypal/ipn", methods=["POST"])
def paypal_ipn():
    data = request.form.to_dict()
    verify = {"cmd": "_notify-validate"}
    verify.update(data)

    if TEST_MODE:
        print("⚙️ TEST_MODE active: skipping PayPal verification.")
        res_text = "VERIFIED"
    else:
        try:
            res = requests.post(PAYPAL_VERIFY, data=verify, timeout=10)
            res_text = res.text.strip()
        except Exception as e:
            print(f"⚠️ Error verifying IPN with PayPal: {e}")
            return "BAD", 400

    log_ipn(data, res_text)

    if res_text != "VERIFIED":
        print(f"❌ Invalid IPN verification: {res_text}")
        return "BAD", 400

    if data.get("payment_status") != "Completed":
        return "OK", 200

    discord_id = data.get("custom")
    months = data.get("item_number")
    payer_email = data.get("payer_email", "unknown")
    gross = data.get("mc_gross", "0")

    if not discord_id or not months:
        return "OK", 200

    # ✅ Update database and clear trial
    existing = get_member(discord_id)
    was_payer = bool(existing and existing[10])
    was_promo_eligible = is_promo_eligible(discord_id) and not has_used_promo(discord_id)

    update_payment(discord_id, months)
    clear_trial_after_payment(discord_id)

    # 💎 Mark promo usage if applicable
    if was_promo_eligible:
        try:
            mark_promo_used(discord_id)
            print(f"🎁 Promo marked as used for Discord ID {discord_id}")
        except Exception as e:
            print(f"⚠️ Failed to mark promo as used for {discord_id}: {e}")


# 🤝 Referral Bonus Logic
    try:
        ref_data = get_member(discord_id)
        referrer_id = ref_data[14] if len(ref_data) > 14 else None
        if referrer_id:
            ref_cfg = config["Referral"] if config.has_section("Referral") else {}

            # Load bonuses from config.ini (fallback to defaults if missing)
            bonus_days = int(ref_cfg.get(
                f"Bonus{months}Month" if months == "1" else f"Bonus{months}Months",
                {"1": 7, "3": 14, "6": 30, "12": 60}.get(str(months), 0)
            ))

            # Always give full bonus — no promo reduction
            if bonus_days > 0:
                conn = sqlite3.connect("data/members.db")
                c = conn.cursor()
                ref_row = get_member(referrer_id)
                if ref_row:
                    base = (
                        datetime.fromisoformat(ref_row[10])
                        if ref_row[10]
                        else datetime.now(timezone.utc)
                    )
                    new_paid_until = base + timedelta(days=bonus_days)
                    c.execute(
                        "UPDATE members SET paid_until=? WHERE discord_id=?",
                        (new_paid_until.isoformat(), str(referrer_id)),
                    )
                    conn.commit()
                    conn.close()

                    msg = f"🎁 Referral bonus applied: {bonus_days} days added for referrer <@{referrer_id}>."
                    print(msg)
                    if ADMIN_WEBHOOK_URL:
                        requests.post(ADMIN_WEBHOOK_URL, json={"content": msg})
    except Exception as e:
        print(f"⚠️ Referral bonus logic failed: {e}")


    # 🔔 Admin messages
    if was_payer:
        msg = f"💰 Renewal verified for {payer_email}: {gross} {CURRENCY} for {months} month(s)."
    else:
        msg = f"💳 Payment verified for {payer_email}: {gross} {CURRENCY} for {months} month(s)."
        if was_promo_eligible:
            msg += " 🎁 (Promo pricing applied — first-time discount)"
    print(msg)
    if ADMIN_WEBHOOK_URL:
        try:
            requests.post(ADMIN_WEBHOOK_URL, json={"content": msg})
        except Exception as e:
            print(f"⚠️ Failed to send admin webhook: {e}")

    from bot.discord_adapter import apply_role, send_admin

    try:
        # announce payment
        if was_payer:
            send_admin(f"💰 Renewal processed for {payer_email} — access extended.")
        else:
            send_admin(f"💳 Payment recorded for {payer_email} — trial cleared and access extended.")

        # try to sync role if Discord enabled
        apply_role(discord_id, "Payer")

    except Exception as e:
        print(f"⚠️ Discord adapter failed to mirror role: {e}")


    return "OK", 200

# ────────────────────────────────
# Thank-you and Cancel pages
# ────────────────────────────────
@app.route("/paypal/thanks")
def paypal_thanks():
    return "<h2>✅ Thank you for your payment!</h2><p>Your access will update soon.</p>"

@app.route("/paypal/cancel")
def paypal_cancel():
    return "<h2>⚠️ Payment cancelled.</h2><p>No money was charged.</p>"

# ────────────────────────────────
# ✅ Casharr System Task API (for WebUI dashboard)
# ────────────────────────────────
from flask import jsonify
from webui.scheduler import scheduler

@app.get("/api/tasks")
def api_get_tasks():
    """Return JSON list of background tasks (WebUI scheduler version)."""
    data = []
    for t in scheduler.tasks:
        data.append({
            "name": t["name"],
            "interval": str(t["interval"]),
            "next_run": t["next"].isoformat(),
            "last_run": t["last_run"].isoformat() if t["last_run"] else None
        })
    return jsonify({"ok": True, "tasks": data})


@app.post("/api/tasks/run")
def api_run_task():
    """Manually trigger a task by name."""
    name = request.json.get("name", "")
    match = next((t for t in scheduler.tasks if t["name"].lower() == name.lower()), None)
    if not match:
        return jsonify({"ok": False, "error": "Task not found"}), 404
    try:
        match["func"]()
        match["last_run"] = datetime.now(timezone.utc)
        return jsonify({"ok": True, "message": f"Task '{name}' executed manually."})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
    
# ────────────────────────────────
# ✅ Casharr System Status API
# ────────────────────────────────

@app.get("/api/status")
def api_status():
    """Return runtime system status for dashboard display."""
    try:
        uptime_sec = int(time.time() - APP_START)
        hours, remainder = divmod(uptime_sec, 3600)
        minutes, seconds = divmod(remainder, 60)
        uptime_str = f"{hours:02d}:{minutes:02d}:{seconds:02d}"

        # Disk usage
        usage = psutil.disk_usage('/')
        disk_info = {
            "total": f"{usage.total / (1024**3):.1f} GB",
            "used": f"{usage.used / (1024**3):.1f} GB",
            "percent": usage.percent
        }

        # Plex & Discord states
        discord_ok = bot.is_ready() if hasattr(bot, "is_ready") else False
        plex_ok = False
        try:
            plex_ok = bool(plex.plex)
        except Exception:
            plex_ok = False

        return {
            "ok": True,
            "uptime": uptime_str,
            "discord_online": discord_ok,
            "plex_connected": plex_ok,
            "disk": disk_info
        }
    except Exception as e:
        return {"ok": False, "error": str(e)}, 500

@app.post("/api/pending/<int:action_id>/approve")
def api_approve_action(action_id):
    from database import resolve_pending_action
    resolve_pending_action(action_id, True)
    return redirect("/pending")

@app.post("/api/pending/<int:action_id>/deny")
def api_deny_action(action_id):
    from database import resolve_pending_action
    resolve_pending_action(action_id, False)
    return redirect("/pending")

@app.get("/api/sync/plex")
def api_sync_plex_preview():
    """Dry-run: show what users would be added from Plex."""
    from plexhelper import PlexHelper
    from database import get_all_members
    plex = PlexHelper(
        config["Plex"].get("URL"),
        config["Plex"].get("Token"),
        [x.strip() for x in config["Plex"].get("Libraries", "").split(",") if x.strip()]
    )

    plex_users = plex.list_users()
    db_members = get_all_members()
    existing_emails = {m[4].lower() for m in db_members if m[4]}  # column 4 = email

    new_users = [u for u in plex_users if u["email"] not in existing_emails]
    return jsonify({"ok": True, "new_count": len(new_users), "new_users": new_users})


@app.post("/api/sync/plex")
def api_sync_plex_commit():
    """Commit Plex → DB sync (adds new users as Lifetime)."""
    from plexhelper import PlexHelper
    from database import save_member
    plex = PlexHelper(
        config["Plex"].get("URL"),
        config["Plex"].get("Token"),
        [x.strip() for x in config["Plex"].get("Libraries", "").split(",") if x.strip()]
    )

    plex_users = plex.list_users()
    added = 0
    for u in plex_users:
        email = u["email"].lower().strip()
        name = u["name"]
        try:
            save_member(
                discord_id=None,
                discord_tag=None,
                first_name=name,
                last_name="",
                email=email,
                mobile="",
                invite_sent_at=None,
                trial_start=None,
                trial_end=None,
                had_trial=0,
                paid_until=None,
                trial_reminder_sent_at=None,
                paid_reminder_sent_at=None,
                used_promo=None,
                referrer=None,
                status="Lifetime",
                origin="sync"
            )
            added += 1
        except Exception:
            pass

    return jsonify({"ok": True, "added": added})
# ────────────────────────────────
# Run Flask standalone (optional)
# ────────────────────────────────
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
