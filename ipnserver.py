# ipnserver.py
from flask import Flask, request
import discord
import requests, os, configparser, asyncio, json, sqlite3
from datetime import datetime, timezone, timedelta
import psutil
import time
from bot import bot, plex

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
app.register_blueprint(webui)   # ✅ register blueprint once
import os
app.secret_key = os.environ.get("CASHARR_SECRET", os.urandom(24))


# ────────────────────────────────
# Load configuration
# ────────────────────────────────
CONFIG_PATH = os.path.join("config", "config.ini")
config = configparser.ConfigParser()
config.read(CONFIG_PATH, encoding="utf-8")

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

    # 🔹 Promote or update user role
    try:
        from bot import bot, PAYER_ROLE, TRIAL_ROLE, INITIAL_ROLE, send_admin

        async def promote_to_payer():
            for g in bot.guilds:
                member = g.get_member(int(discord_id))
                if not member:
                    continue
                payer_role = discord.utils.get(g.roles, name=PAYER_ROLE)
                trial_role = discord.utils.get(g.roles, name=TRIAL_ROLE)
                initial_role = discord.utils.get(g.roles, name=INITIAL_ROLE)
                if trial_role in member.roles:
                    await member.remove_roles(trial_role)
                if initial_role in member.roles:
                    await member.remove_roles(initial_role)
                if payer_role and payer_role not in member.roles:
                    await member.add_roles(payer_role)
                    await send_admin(f"💳 Payment recorded for {member.mention} — trial cleared and access extended.")
                elif was_payer:
                    await send_admin(f"💰 Renewal processed for {member.mention} — access extended.")
                break

        asyncio.run_coroutine_threadsafe(promote_to_payer(), bot.loop)
    except Exception as e:
        print(f"⚠️ Failed to promote/update payer: {e}")

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
from bot import bot as discord_bot
from bot.tasks.task_registry import get_all as get_all_tasks, has_task, run_once as run_task_once

@app.get("/api/tasks")
def api_get_tasks():
    """Return JSON list of all registered background tasks for dashboard."""
    try:
        tasks_data = get_all_tasks()
        return jsonify({"ok": True, "tasks": tasks_data})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


@app.post("/api/tasks/run")
def api_run_task():
    """Trigger a single task manually by name."""
    try:
        data = request.get_json(force=True)
        name = data.get("name", "")
        if not name:
            return jsonify({"ok": False, "error": "Missing task name"}), 400
        if not has_task(name):
            return jsonify({"ok": False, "error": f"Unknown task: {name}"}), 404

        run_task_once(discord_bot.loop, name)
        return jsonify({"ok": True, "message": f"Task '{name}' triggered successfully."})
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


# ────────────────────────────────
# Run Flask standalone (optional)
# ────────────────────────────────
if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
