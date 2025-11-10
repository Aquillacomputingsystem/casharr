# webui/app.py
from flask import (
    Blueprint, render_template, send_from_directory, abort,
    request, jsonify, flash, redirect, url_for, Response, session
)
import os, shutil, requests, glob, asyncio, configparser, discord, sqlite3
from datetime import datetime, timezone, timedelta
import hashlib
import xml.etree.ElementTree as ET
import psutil, time, json

from reportlab.lib.pagesizes import letter
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet

# ───────────────────────────────
# App / Helpers / DB imports
# ───────────────────────────────
from plexhelper import PlexHelper
from helpers.emailer import send_email
from loghelper import LOG_DIR, logger

from database import (
    DB_PATH, get_all_members, get_member, save_member,
    start_trial, end_trial, add_or_update_member, delete_member,
    update_member_role
)
from bot import (
    client as bot,
    ADMIN_ROLE, INITIAL_ROLE, TRIAL_ROLE, PAYER_ROLE, LIFETIME_ROLE,
    send_admin, plex, TRIAL_DAYS
)

# ───────────────────────────────
# Define the WebUI blueprint
# ───────────────────────────────
webui = Blueprint(
    "webui",
    __name__,
    template_folder="templates",
    static_folder="static",
    static_url_path="/webui/static",
)

EXPORTS_DIR = "exports"
os.makedirs(EXPORTS_DIR, exist_ok=True)
os.makedirs(LOG_DIR, exist_ok=True)

# ───────────────────────────────
# SESSION + LOGIN SECURITY
# ───────────────────────────────
SECRET_KEY = os.environ.get("CASHARR_SECRET", "casharr_dev_key")
webui.secret_key = SECRET_KEY


def get_admin_credentials():
    """Return stored (username, password_hash) from config.ini."""
    cfg = configparser.ConfigParser()
    cfg.read(os.path.join("config", "config.ini"), encoding="utf-8")

    user = cfg.get("WebUI", "AdminUser", fallback="").strip()
    pw = cfg.get("WebUI", "AdminPass", fallback="").strip()
    pw_hash = hashlib.sha256(pw.encode()).hexdigest() if pw else ""
    return user, pw_hash


def login_required(f):
    """Decorator to protect routes if login is enabled."""
    from functools import wraps
    @wraps(f)
    def decorated_function(*args, **kwargs):
        user, pw_hash = get_admin_credentials()
        if not user or not pw_hash:
            return f(*args, **kwargs)
        if not session.get("logged_in"):
            return redirect(url_for("webui.login", next=request.path))
        return f(*args, **kwargs)
    return decorated_function


@webui.before_request
def enforce_login_on_first_visit():
    public_routes = ["webui.login", "webui.logout", "webui.static"]
    if request.endpoint in public_routes:
        return
    user, pw_hash = get_admin_credentials()
    if user and pw_hash and not session.get("logged_in"):
        return redirect(url_for("webui.login", next=request.path))

# ───────────────────────────────
# Dashboard
# ───────────────────────────────
@webui.route("/")
@webui.route("/dashboard")
def dashboard():
    rows = get_all_members()
    # make comparisons timezone-neutral
    from datetime import datetime

    def _to_naive(dt_str):
        if not dt_str:
            return None
        try:
            return datetime.fromisoformat(dt_str).replace(tzinfo=None)
        except Exception:
            return None

    now_naive = datetime.now().replace(tzinfo=None)

    total = len(rows)
    active_trials = sum(
        1 for r in rows
        if r[8] and (te := _to_naive(r[8])) and te > now_naive
    )
    active_payers = sum(
        1 for r in rows
        if r[10] and (pu := _to_naive(r[10])) and pu > now_naive
    )
    expired = sum(
        1 for r in rows
        if (
            (r[8] and (te := _to_naive(r[8])) and te < now_naive)
            or (r[10] and (pu := _to_naive(r[10])) and pu < now_naive)
        )
    )


    cfg = configparser.ConfigParser()
    cfg.read(os.path.join("config", "config.ini"), encoding="utf-8")

    trial_days = cfg.get("Trial", "DurationDays", fallback="").strip()
    referral_enabled = cfg.getboolean("Referral", "Enabled", fallback=False)
    referral_bonus = cfg.get("Referral", "Bonus1Month", fallback="").strip()
    promo_enabled = cfg.getboolean("Promo", "Enabled", fallback=False)
    promo_note = cfg.get("Promo", "Note", fallback="").strip('"')
    reminders_enabled = cfg.getboolean("Reminders", "Enabled", fallback=False)
    reminder_days = cfg.get("Reminders", "DaysBeforeExpiry", fallback="").strip()
    access_mode = cfg.get("AccessMode", "Mode", fallback="Manual").strip()

    stats = {"total": total, "active_trials": active_trials, "active_payers": active_payers, "expired": expired}

    return render_template(
        "dashboard.html",
        title="Dashboard | Casharr",
        stats=stats,
        trial_days=trial_days,
        referral_enabled=referral_enabled,
        referral_bonus=referral_bonus,
        promo_enabled=promo_enabled,
        promo_note=promo_note,
        reminders_enabled=reminders_enabled,
        reminder_days=reminder_days,
        access_mode=access_mode,
    )

# ───────────────────────────────
# API: simple stats + logs
# ───────────────────────────────
@webui.route("/api/stats")
def api_stats():
    rows = get_all_members()
    now = datetime.now(timezone.utc)
    total = len(rows)
    active_trials = sum(1 for r in rows if r[8] and datetime.fromisoformat(r[8]) > now)
    active_payers = sum(1 for r in rows if r[10] and datetime.fromisoformat(r[10]) > now)
    expired = sum(
        1 for r in rows
        if ((r[8] and datetime.fromisoformat(r[8]) < now) or (r[10] and datetime.fromisoformat(r[10]) < now))
    )
    return jsonify({"total": total, "active_trials": active_trials, "active_payers": active_payers, "expired": expired})


@webui.route("/api/logs")
def api_logs_list():
    files = []
    for f in sorted(os.listdir(LOG_DIR), key=lambda x: os.path.getmtime(os.path.join(LOG_DIR, x)), reverse=True):
        if f.endswith(".log"):
            path = os.path.join(LOG_DIR, f)
            files.append({"name": f, "size": os.path.getsize(path), "mtime": os.path.getmtime(path)})
    return jsonify({"files": files})


@webui.route("/api/logs/<logname>")
def api_log_content(logname):
    safe = os.path.basename(logname)
    path = os.path.join(LOG_DIR, safe)
    if not os.path.isfile(path):
        abort(404)
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        data = f.readlines()[-1000:]
    return Response("".join(data), mimetype="text/plain; charset=utf-8")

# ───────────────────────────────
# Login / Logout
# ───────────────────────────────
@webui.route("/login", methods=["GET", "POST"])
def login():
    user, pw_hash = get_admin_credentials()
    if not user or not pw_hash:
        return redirect(url_for("webui.dashboard"))

    error = None
    if request.method == "POST":
        entered_user = request.form.get("username", "")
        entered_pass = request.form.get("password", "")
        entered_hash = hashlib.sha256(entered_pass.encode()).hexdigest()
        if entered_user == user and entered_hash == pw_hash:
            session["logged_in"] = True
            session.permanent = True
            session["user"] = entered_user
            flash("✅ Logged in successfully!", "success")
            next_url = request.args.get("next") or url_for("webui.dashboard")
            return redirect(next_url)
        else:
            error = "❌ Invalid username or password."
    return render_template("login.html", title="Login | Casharr", error=error)


@webui.route("/logout")
def logout():
    session.clear()
    flash("🔒 Logged out successfully.", "info")
    return redirect(url_for("webui.login"))

# ───────────────────────────────
# Config: Plex
# ───────────────────────────────
@webui.route("/config/plex", methods=["GET", "POST"])
def config_plex():
    CONFIG_PATH = os.path.join("config", "config.ini")
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_PATH, encoding="utf-8")

    if "Plex" not in cfg: cfg["Plex"] = {}
    if "AccessMode" not in cfg: cfg["AccessMode"] = {}

    if request.method == "POST":
        try:
            cfg["Plex"]["URL"] = request.form.get("URL", "").strip()
            cfg["Plex"]["Token"] = request.form.get("Token", "").strip()
            cfg["Plex"]["Libraries"] = request.form.get("Libraries", "").strip()
            cfg["AccessMode"]["Mode"] = request.form.get("AccessMode", "Auto").capitalize()
            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                cfg.write(f)
            flash("✅ Plex configuration updated successfully!", "success")
            return redirect(url_for("webui.config_plex"))
        except Exception as e:
            return f"<pre>⚠️ Error saving Plex config: {type(e).__name__}: {e}</pre>", 500

    plex_config = cfg["Plex"]
    access_mode = cfg.get("AccessMode", "Mode", fallback="Auto").strip().capitalize()
    return render_template("config_plex.html", title="Config | Plex", config=plex_config, access_mode=access_mode)


@webui.route("/config/plex/test", methods=["POST"])
def test_plex_connection():
    CONFIG_PATH = os.path.join("config", "config.ini")
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_PATH, encoding="utf-8")

    try:
        if "Plex" not in cfg:
            return jsonify({"status": "error", "error": "Missing Plex section in config.ini"}), 400

        url = cfg["Plex"].get("URL", "")
        token = cfg["Plex"].get("Token", "")
        libs = [s.strip() for s in cfg["Plex"].get("Libraries", "").split(",") if s.strip()]

        if not url or not token:
            return jsonify({"status": "error", "error": "URL or Token missing"}), 400

        plex = PlexHelper(url, token, libs)
        server_name = plex.plex.friendlyName
        libraries = [s.title for s in plex.plex.library.sections()]
        return jsonify({"status": "ok", "server": server_name, "libraries": libraries})
    except Exception as e:
        return jsonify({"status": "error", "error": str(e)}), 500

# ───────────────────────────────
# Config: generic handler
# ───────────────────────────────
@webui.route("/config/<section>", methods=["GET", "POST"])
def config_section(section):
    CONFIG_PATH = os.path.join("config", "config.ini")
    cfg = configparser.ConfigParser()
    with open(CONFIG_PATH, "r", encoding="utf-8", errors="replace") as f:
        cfg.read_file(f)

    sections_lower = {s.lower(): s for s in cfg.sections()}
    section_key = sections_lower.get(section.lower())
    if not section_key:
        abort(404)

    if section_key.lower() == "reminders":
        merged = {}
        for name in ("reminders", "messages", "trial"):
            real = sections_lower.get(name)
            if real: merged.update(cfg[real])
    else:
        merged = dict(cfg[section_key])
    merged = {k.lower(): v for k, v in merged.items()}

    if request.method == "POST":
        form = request.form.to_dict()
        if section_key.lower() == "reminders":
            for key, value in form.items():
                key_lower = key.lower()
                if key_lower in ["enabled", "daysbeforeexpiry", "notifydiscord", "notifyemail", "notifysms"]:
                    target = sections_lower.get("reminders")
                elif key_lower in ["welcome", "trialreminder", "paidreminder"]:
                    target = sections_lower.get("messages")
                elif key_lower in ["durationdays"]:
                    target = sections_lower.get("trial")
                else:
                    target = sections_lower.get("reminders")
                if target:
                    cfg[target][key] = value
        else:
            for key, value in form.items():
                if key in cfg[section_key]:
                    cfg[section_key][key] = value
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            cfg.write(f)
        flash("✅ Configuration saved successfully!", "success")
        return redirect(request.url)

    return render_template(f"config_{section.lower()}.html", title=f"Config | {section.title()}", config=merged)

# ───────────────────────────────
# CONFIGURATION: Payments + Referral
# ───────────────────────────────
@webui.route("/config/payments", methods=["GET", "POST"])
def config_payments():
    CONFIG_PATH = os.path.join("config", "config.ini")
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_PATH, encoding="utf-8")

    for sec in ["Pricing", "Promo", "PayPal", "Site", "Referral"]:
        if sec not in cfg: cfg[sec] = {}

    if request.method == "POST":
        try:
            cfg["Pricing"]["DefaultCurrency"] = request.form.get("DefaultCurrency", "AUD").strip()
            cfg["Pricing"]["1Month"] = request.form.get("1Month", "0").strip()
            cfg["Pricing"]["3Months"] = request.form.get("3Months", "0").strip()
            cfg["Pricing"]["6Months"] = request.form.get("6Months", "0").strip()
            cfg["Pricing"]["12Months"] = request.form.get("12Months", "0").strip()

            cfg["Promo"]["Enabled"] = request.form.get("PromoEnabled", "false").strip()
            cfg["Promo"]["Discount1Month"] = request.form.get("Discount1Month", "0").strip()
            cfg["Promo"]["Discount3Months"] = request.form.get("Discount3Months", "0").strip()
            cfg["Promo"]["Discount6Months"] = request.form.get("Discount6Months", "0").strip()
            cfg["Promo"]["Discount12Months"] = request.form.get("Discount12Months", "0").strip()
            cfg["Promo"]["Note"] = request.form.get("PromoNote", "").strip()

            cfg["Referral"]["Enabled"] = request.form.get("ReferralEnabled", "true").strip()
            cfg["Referral"]["Bonus1Month"] = request.form.get("Bonus1Month", "7").strip()
            cfg["Referral"]["Bonus3Months"] = request.form.get("Bonus3Months", "14").strip()
            cfg["Referral"]["Bonus6Months"] = request.form.get("Bonus6Months", "30").strip()
            cfg["Referral"]["Bonus12Months"] = request.form.get("Bonus12Months", "60").strip()

            cfg["PayPal"]["Mode"] = request.form.get("Mode", "live").strip()
            cfg["PayPal"]["BusinessEmail"] = request.form.get("BusinessEmail", "").strip()
            cfg["PayPal"]["PaymentBaseLink"] = request.form.get("PaymentBaseLink", "").strip()
            cfg["PayPal"]["IPN_URL"] = request.form.get("IPN_URL", "").strip()
            cfg["PayPal"]["IPNListenPort"] = request.form.get("IPNListenPort", "5000").strip()

            cfg["Site"]["Domain"] = request.form.get("Domain", "").strip()

            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                cfg.write(f)
            flash("✅ Payments & PayPal configuration updated successfully!", "success")
            return redirect(url_for("webui.config_payments"))
        except Exception as e:
            return f"<pre>⚠️ Error saving config: {type(e).__name__}: {e}</pre>", 500

    merged = {}
    for sec in ["Pricing", "Promo", "PayPal", "Referral", "Site"]:
        for k, v in cfg[sec].items():
            merged[k.lower()] = v
    return render_template("config_payments.html", title="Config | Payments", config=merged)

# ───────────────────────────────
# CONFIGURATION: System Settings (incl. SMTP)
# ───────────────────────────────
@webui.route("/config/settings", methods=["GET", "POST"])
def config_settings():
    CONFIG_PATH = os.path.join("config", "config.ini")
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_PATH, encoding="utf-8")

    for sec in ["AccessMode", "System", "WebUI", "Logging", "SMTP"]:
        if sec not in cfg: cfg[sec] = {}

    if request.method == "POST":
        cfg["AccessMode"]["Mode"] = request.form.get("AccessMode", "Auto").capitalize()

        cfg["System"]["ExternalAddress"] = request.form.get("ExternalAddress", "").strip()
        cfg["System"]["Port"] = request.form.get("Port", "5000").strip()
        cfg["System"]["AllowExternal"] = request.form.get("AllowExternal", "false").lower()

        cfg["WebUI"]["AdminUser"] = request.form.get("AdminUser", "").strip()
        cfg["WebUI"]["AdminPass"] = request.form.get("AdminPass", "").strip()

        cfg["Logging"]["RetentionDays"] = request.form.get("LogRetention", "30").strip()
        cfg["System"]["Debug"] = request.form.get("Debug", "false").lower()

        # SMTP (Email) settings
        cfg["SMTP"]["Enabled"] = request.form.get("SMTPEnabled", "false").lower()
        cfg["SMTP"]["Server"] = request.form.get("SMTPServer", "").strip()
        cfg["SMTP"]["User"] = request.form.get("SMTPUser", "").strip()
        cfg["SMTP"]["Pass"] = request.form.get("SMTPPass", "").strip()
        cfg["SMTP"]["To"] = request.form.get("SMTPTo", "").strip()

        # SMS Gateway settings
        if "SMS" not in cfg:
            cfg["SMS"] = {}
        cfg["SMS"]["Enabled"] = request.form.get("SMSEnabled", "false").lower()
        cfg["SMS"]["GatewayURL"] = request.form.get("SMSGatewayURL", "").strip()
        cfg["SMS"]["Token"] = request.form.get("SMSToken", "").strip()
        cfg["SMS"]["From"] = request.form.get("SMSFrom", "Casharr").strip()


        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            cfg.write(f)
        flash("✅ System settings updated successfully!", "success")
        return redirect(url_for("webui.config_settings"))

    access_mode = cfg.get("AccessMode", "Mode", fallback="Auto").strip().capitalize()
    ext_address = cfg.get("System", "ExternalAddress", fallback="")
    port = cfg.get("System", "Port", fallback="5000")
    allow_external = cfg.getboolean("System", "AllowExternal", fallback=False)
    admin_user = cfg.get("WebUI", "AdminUser", fallback="")
    admin_pass = cfg.get("WebUI", "AdminPass", fallback="")
    log_retention = cfg.get("Logging", "RetentionDays", fallback="30")
    debug_mode = cfg.getboolean("System", "Debug", fallback=False)

    smtp_enabled = cfg.getboolean("SMTP", "Enabled", fallback=False)
    smtp_server = cfg.get("SMTP", "Server", fallback="")
    smtp_user = cfg.get("SMTP", "User", fallback="")
    smtp_pass = cfg.get("SMTP", "Pass", fallback="")
    smtp_to = cfg.get("SMTP", "To", fallback="")

    sms_enabled = cfg.getboolean("SMS", "Enabled", fallback=False)
    sms_gateway = cfg.get("SMS", "GatewayURL", fallback="")
    sms_token = cfg.get("SMS", "Token", fallback="")
    sms_from = cfg.get("SMS", "From", fallback="Casharr")

    return render_template(
        "config_settings.html",
        title="Config | Settings",
        access_mode=access_mode,
        ext_address=ext_address,
        port=port,
        allow_external=allow_external,
        admin_user=admin_user,
        admin_pass=admin_pass,
        log_retention=log_retention,
        debug_mode=debug_mode,
        smtp_enabled=smtp_enabled,
        smtp_server=smtp_server,
        smtp_user=smtp_user,
        smtp_pass=smtp_pass,
        smtp_to=smtp_to,
        sms_enabled=sms_enabled,
        sms_gateway=sms_gateway,
        sms_token=sms_token,
        sms_from=sms_from
    )

# ───────────────────────────────
# Config: Discord
# ───────────────────────────────
@webui.route("/config/discord", methods=["GET", "POST"])
def config_discord():
    CONFIG_PATH = os.path.join("config", "config.ini")
    cfg = configparser.ConfigParser()
    cfg.read(CONFIG_PATH, encoding="utf-8")

    if "Discord" not in cfg: cfg["Discord"] = {}

    if request.method == "POST":
        try:
            cfg["Discord"]["BotToken"] = request.form.get("BotToken", "").strip()
            cfg["Discord"]["AdminChannelID"] = request.form.get("AdminChannelID", "").strip()
            cfg["Discord"]["InitialRole"] = request.form.get("InitialRole", "").strip()
            cfg["Discord"]["TrialRole"] = request.form.get("TrialRole", "").strip()
            cfg["Discord"]["PayerRole"] = request.form.get("PayerRole", "").strip()
            cfg["Discord"]["LifetimeRole"] = request.form.get("LifetimeRole", "").strip()
            cfg["Discord"]["AdminRole"] = request.form.get("AdminRole", "").strip()

            with open(CONFIG_PATH, "w", encoding="utf-8") as f:
                cfg.write(f)
            flash("✅ Discord configuration updated successfully!", "success")
            return redirect(url_for("webui.config_discord"))
        except Exception as e:
            return f"<pre>⚠️ Error saving Discord config: {type(e).__name__}: {e}</pre>", 500

    merged = {k.lower(): v for k, v in cfg["Discord"].items()}
    return render_template("config_discord.html", title="Config | Discord", config=merged)

# ───────────────────────────────
# Members Page
# ───────────────────────────────
@webui.route("/members")
def members():
    return render_template("members.html", title="Members | Casharr")

# ───────────────────────────────
# Discord Role & Member Helpers
# ───────────────────────────────
def _find_member_across_guilds(discord_id: int):
    for g in bot.guilds:
        m = g.get_member(int(discord_id))
        if m: return g, m
    return None, None

def _roles_for_guild(guild):
    return (
        discord.utils.get(guild.roles, name=INITIAL_ROLE),
        discord.utils.get(guild.roles, name=TRIAL_ROLE),
        discord.utils.get(guild.roles, name=PAYER_ROLE),
        discord.utils.get(guild.roles, name=LIFETIME_ROLE),
        discord.utils.get(guild.roles, name=ADMIN_ROLE),
    )

async def _discord_set_role(discord_id: int, target_role: str):
    guild, member = _find_member_across_guilds(discord_id)
    if not guild or not member:
        return {"ok": False, "error": "Member not found in any guild."}
    init_r, trial_r, payer_r, life_r, _ = _roles_for_guild(guild)
    current = [r for r in [init_r, trial_r, payer_r, life_r] if r and r in member.roles]
    if current:
        try:
            await member.remove_roles(*current, reason="Casharr WebUI role update")
        except Exception as e:
            return {"ok": False, "error": f"Failed removing roles: {e}"}
    add_map = {INITIAL_ROLE: init_r, TRIAL_ROLE: trial_r, PAYER_ROLE: payer_r, LIFETIME_ROLE: life_r}
    add_role = add_map.get(target_role)
    if add_role:
        try:
            await member.add_roles(add_role, reason="Casharr WebUI role update")
        except Exception as e:
            return {"ok": False, "error": f"Failed adding role: {e}"}
    return {"ok": True}

def _compute_status(row, member, guild):
    import datetime as dtlib

    def _to_naive(value):
        if not value:
            return None
        if isinstance(value, str):
            try:
                value = dtlib.datetime.fromisoformat(value)
            except Exception:
                return None
        return value.replace(tzinfo=None)

    paid_until = _to_naive(row[10] if len(row) > 10 else None)
    trial_end  = _to_naive(row[8] if len(row) > 8 else None)
    now_naive  = dtlib.datetime.now().replace(tzinfo=None)

    # check Discord roles first
    if guild and member:
        init_r, trial_r, payer_r, life_r, _ = _roles_for_guild(guild)
        if life_r and life_r in member.roles:
            return "Lifetime"
        if payer_r and payer_r in member.roles:
            return "Payer"
        if trial_r and trial_r in member.roles:
            return "Trial"

    # fallback based on database fields
    if paid_until and paid_until > now_naive:
        return "Payer"
    if trial_end and trial_end > now_naive:
        return "Trial"
    return "Expired"
    def parse_iso_safe(val):
        if not val: return None
        try: return datetime.fromisoformat(val)
        except Exception: return None
    now = datetime.now(timezone.utc)
    paid_until = parse_iso_safe(row[10] if len(row) > 10 else None)
    trial_end = parse_iso_safe(row[8] if len(row) > 8 else None)

    if guild and member:
        init_r, trial_r, payer_r, life_r, _ = _roles_for_guild(guild)
        if life_r and life_r in member.roles: return "Lifetime"
        if payer_r and payer_r in member.roles: return "Payer"
        if trial_r and trial_r in member.roles: return "Trial"

    if paid_until and paid_until > now: return "Payer"
    if trial_end and trial_end > now: return "Trial"
    return "Expired"

# ───────────────────────────────
# 📡 Members JSON API
# ───────────────────────────────
@webui.route("/api/members", methods=["GET"])
def api_members():
    import datetime as dtlib  # move to top of function
    rows = get_all_members()
    out = []

    def parse_iso_safe(val):
        if not val:
            return None
        try:
            return dtlib.datetime.fromisoformat(val)
        except Exception:
            return None

    # timezone-safe comparison helpers
    def _to_naive(value):
        if not value:
            return None
        if isinstance(value, str):
            try:
                value = dtlib.datetime.fromisoformat(value)
            except Exception:
                return None
        return value.replace(tzinfo=None)

    now_naive = dtlib.datetime.now().replace(tzinfo=None)

    for r in rows:
        # Safely handle missing or invalid Discord IDs
        try:
            did = int(r[0]) if r[0] else 0
        except Exception:
            did = 0

        guild, member = _find_member_across_guilds(did)
        role_display = "—"
        if guild and member:
            init_r, trial_r, payer_r, life_r, _ = _roles_for_guild(guild)
            if life_r and life_r in member.roles:
                role_display = LIFETIME_ROLE
            elif payer_r and payer_r in member.roles:
                role_display = PAYER_ROLE
            elif trial_r and trial_r in member.roles:
                role_display = TRIAL_ROLE
            elif init_r and init_r in member.roles:
                role_display = INITIAL_ROLE
            else:
                role_display = "No Access"
        else:
            paid_until = parse_iso_safe(r[10] if len(r) > 10 else None)
            trial_end = parse_iso_safe(r[8] if len(r) > 8 else None)

            pu = _to_naive(paid_until)
            te = _to_naive(trial_end)

            if pu and pu > now_naive:
                role_display = PAYER_ROLE
            elif te and te > now_naive:
                role_display = TRIAL_ROLE
            else:
                role_display = INITIAL_ROLE

        status = _compute_status(r, member, (guild or (bot.guilds[0] if bot.guilds else None)))
        out.append({
            "discord_id": r[0] or "",
            "discord_tag": r[1] or "",
            "first_name": r[2] or "",
            "last_name": r[3] or "",
            "email": r[4] or "",
            "mobile": r[5] or "",
            "trial_end": r[8] or "",
            "paid_until": r[10] or "",
            "referrer_id": r[14] if len(r) > 14 else None,
            "origin": r[17] if len(r) > 17 else None,
            "discord_role": role_display,
            "status": status,
        })

    return jsonify({"members": out})

@webui.route("/api/member/<discord_id>/role", methods=["POST"])
def api_member_set_role(discord_id):
    payload = request.get_json(silent=True) or {}
    role = payload.get("role")
    if not role:
        return jsonify({"ok": False, "error": "Role is required."}), 400

    try:
        update_member_role(discord_id, str(role))
        logger.info("Updated role for %s to %s", discord_id, role)
        return jsonify({"ok": True})
    except ValueError as exc:
        return jsonify({"ok": False, "error": str(exc)}), 400
    except Exception:
        logger.exception("Failed to update role for %s", discord_id)
        return jsonify({"ok": False, "error": "Internal server error."}), 500

    
@webui.route("/api/member/<discord_id>", methods=["GET"])
def api_member_get(discord_id):
    """Return full member details for modal view."""
    member = get_member(discord_id)
    if not member:
        return jsonify({"ok": False, "error": "Member not found"}), 404
    fields = [
        "discord_id","discord_tag","first_name","last_name","email",
        "mobile","join_date","trial_start","trial_end","paid_until",
        "role","referrer_id","origin","status"
    ]
    data = {fields[i]: member[i] if i < len(member) else None for i in range(len(fields))}
    return jsonify({"ok": True, "member": data})

@webui.route("/api/member/<discord_id>/delete", methods=["POST"])
def api_member_delete(discord_id):
    """Remove a member from DB, Plex, and Discord (if enabled)."""
    import asyncio
    import configparser
    import os
    from plexhelper import PlexHelper
    from database import delete_member, get_member

    cfg = configparser.ConfigParser()
    cfg.read(os.path.join("config", "config.ini"), encoding="utf-8")

    discord_enabled = cfg.getboolean("Bot", "DiscordEnabled", fallback=False)
    plex_enabled = cfg.getboolean("Plex", "Enabled", fallback=True)

    # Email may be provided directly from frontend (in case member lookup fails)
    email = request.form.get("email", "").strip() or None

    # Try to load from DB if possible
    member = get_member(discord_id) if discord_id not in ("", "None", None, "noid") else None

    if member:
        email = email or (member[4] if len(member) > 4 else None)
        discord_tag = member[1] if len(member) > 1 else None
        first_name = member[2] if len(member) > 2 else None
        last_name = member[3] if len(member) > 3 else None
    else:
        discord_tag = first_name = last_name = None

    removed = []
    errors = []

    # 1️⃣ Plex removal
    if plex_enabled and email:
        try:
            plex_url = cfg.get("Plex", "BaseURL", fallback=None)
            plex_token = cfg.get("Plex", "Token", fallback=None)
            plex_libs = [l.strip() for l in cfg.get("Plex", "Libraries", fallback="Movies,TV").split(",")]
            plex = PlexHelper(plex_url, plex_token, plex_libs)
            plex.remove_user(email)
            removed.append("Plex")
            logger.info(f"✅ Removed {email} from Plex")
        except Exception as e:
            logger.warning(f"⚠️ Plex removal failed for {email}: {e}")
            errors.append(f"Plex: {e}")

    # 2️⃣ Discord removal
    if discord_enabled and discord_id not in ("", "None", None, "noid"):
        try:
            import main as bot_main
            loop = asyncio.get_event_loop()
            for g in bot_main.bot.guilds:
                member_obj = g.get_member(int(discord_id))
                if member_obj:
                    asyncio.run_coroutine_threadsafe(
                        member_obj.kick(reason="Removed via Casharr WebUI"), loop
                    )
                    removed.append("Discord")
                    logger.info(f"✅ Kicked Discord user {member_obj.name} ({discord_id}) from {g.name}")
                    break
        except Exception as e:
            logger.warning(f"⚠️ Discord removal failed for {discord_id}: {e}")
            errors.append(f"Discord: {e}")

    # 3️⃣ Database removal (always)
    try:
        deleted = delete_member(discord_id=discord_id, email=email)
        if deleted:
            removed.append("Database")
            logger.info(f"✅ Removed from database ({discord_id or email})")
        else:
            logger.warning(f"⚠️ No DB record found for {discord_id or email}")
    except Exception as e:
        logger.exception(f"DB removal failed for {discord_id or email}")
        errors.append(f"DB: {e}")

    # 4️⃣ Response
    summary = f"Removed {first_name or ''} {last_name or ''} ({email or 'N/A'}) from {', '.join(removed)}"
    logger.info(summary)

    if errors:
        return jsonify({"ok": False, "error": '; '.join(errors), "removed": removed}), 500

    return jsonify({"ok": True, "removed": removed})

# ─────────────────────────────
# API: Generate Invite / Onboarding Token
# ─────────────────────────────
@webui.route("/api/invite", methods=["POST"])
def api_invite():
    """Admin endpoint to create onboarding invite + return shareable link/QR."""
    from database import generate_join_token, get_member
    from helpers.emailer import send_email
    from helpers.sms import send_sms
    import secrets, qrcode, io, base64

    data = request.get_json(silent=True) or {}
    discord_id = str(data.get("discord_id", "")).strip() or secrets.token_hex(4)
    email = str(data.get("email", "")).strip()
    mobile = str(data.get("mobile", "")).strip()

    token = generate_join_token(discord_id)
    cfg = configparser.ConfigParser()
    cfg.read(os.path.join("config", "config.ini"), encoding="utf-8")
    domain = cfg.get("Site", "Domain", fallback="http://localhost:5000").rstrip("/")
    join_url = f"{domain}/join/{token}"

    # Generate QR as base64
    qr = qrcode.QRCode(box_size=5, border=1)
    qr.add_data(join_url)
    qr.make(fit=True)
    img = qr.make_image(fill_color="black", back_color="white")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode()

    subject = "You're invited to join Casharr!"
    msg = f"Welcome!\nPlease complete your setup:\n{join_url}"

    # Send notifications using existing systems
    if email:
        try:
            send_email(subject, msg, to=email)
        except Exception as e:
            print(f"⚠️ Email invite failed: {e}")
    if mobile:
        try:
            send_sms(mobile, msg)
        except Exception as e:
            print(f"⚠️ SMS invite failed: {e}")

    return jsonify({"ok": True, "url": join_url, "qr_base64": qr_b64})

# ─────────────────────────────
# Public Onboarding Page
# ─────────────────────────────
# ─────────────────────────────
# Public Onboarding Page (Referral-aware)
# ─────────────────────────────
@webui.route("/join/<token>", methods=["GET", "POST"])
def join_page(token):
    """Public onboarding page for invited or referred users."""
    from database import get_member_by_token, save_member, apply_referral_bonus
    from helpers.emailer import send_email
    from helpers.sms import send_sms
    import sqlite3

    member = get_member_by_token(token)
    if not member:
        return "❌ Invalid or expired invite.", 404

    cfg = configparser.ConfigParser()
    cfg.read(os.path.join("config", "config.ini"), encoding="utf-8")
    discord_enabled = cfg.getboolean("Discord", "Enabled", fallback=False)
    discord_invite = cfg.get("Discord", "InviteLink", fallback="")
    referral_cfg = cfg["Referral"] if cfg.has_section("Referral") else {}
    trial_cfg = cfg["Trial"] if cfg.has_section("Trial") else {}

    if request.method == "POST":
        first = request.form.get("first_name", "").strip()
        last = request.form.get("last_name", "").strip()
        email = request.form.get("email", "").strip()
        mobile = request.form.get("mobile", "").strip()
        referrer_id = request.args.get("ref", "").strip()

        save_member(member[0], first_name=first, last_name=last, email=email, mobile=mobile, origin="invite")

        # Mark joined
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("UPDATE members SET join_status='completed' WHERE join_token=?", (token,))
        conn.commit()
        conn.close()

        # 🏆 Apply referral rewards if ref param + enabled
        if cfg.getboolean("Referral", "enabled", fallback=False) and referrer_id:
            apply_referral_bonus(referrer_id, member[0], referral_cfg, trial_cfg)

            # Notify admin or referrer
            msg = f"🎁 Referral Complete: {first} {last} joined via {referrer_id}. Bonus applied!"
            try:
                send_email("Referral Complete", msg, cfg.get("SMTP", "To", fallback=""))
            except Exception as e:
                print(f"⚠️ Email notify failed: {e}")
            try:
                send_sms(cfg.get("SMS", "TestNumber", fallback=""), msg)
            except Exception as e:
                print(f"⚠️ SMS notify failed: {e}")

        return render_template("join_success.html", title="Welcome | Casharr")

    return render_template("join.html",
                           title="Join | Casharr",
                           token=token,
                           discord_enabled=discord_enabled,
                           discord_invite=discord_invite)

# ─────────────────────────────
# Public Referral Portal
# ─────────────────────────────
@webui.route("/referral", methods=["GET", "POST"])
def referral_portal():
    """
    Public page where existing members can enter their email and
    receive a once-off referral QR / link for inviting friends.
    """
    from database import get_member_by_email, generate_referral_token
    import qrcode, io, base64

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        member = get_member_by_email(email)
        if not member:
            return render_template("referral.html", error="Email not found in system.")

        referrer_id = member[0]
        token = generate_referral_token(referrer_id)

        cfg = configparser.ConfigParser()
        cfg.read(os.path.join("config", "config.ini"), encoding="utf-8")
        domain = cfg.get("Site", "Domain", fallback="http://localhost:5000").rstrip("/")
        join_url = f"{domain}/join/{token}?ref={referrer_id}"

        # Build QR (base64)
        qr = qrcode.QRCode(box_size=5, border=1)
        qr.add_data(join_url)
        qr.make(fit=True)
        img = qr.make_image(fill_color="black", back_color="white")
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        qr_b64 = base64.b64encode(buf.getvalue()).decode()

        return render_template("referral_success.html", join_url=join_url, qr_b64=qr_b64)

    return render_template("referral.html")

# ─────────────────────────────
# Unified Messaging & PayLink API (Enhanced)
# ─────────────────────────────
@webui.route("/api/message/<target>", methods=["POST"])
def api_message(target):
    groups = data.get("groups", [])
    """
    Unified messaging endpoint for WebUI.
    Sends messages through any enabled notification system (Discord, Email, SMS).
    Target may be a single member's Discord ID or 'all' for broadcast.
    """
    import asyncio
    from helpers.emailer import send_email
    from helpers.sms import send_sms
    from database import get_member, get_all_members
    from bot import bot
    import configparser, os

    # ── Parse incoming data
    data = request.get_json(silent=True) or {}
    subject = data.get("subject", "Message from Casharr Admin").strip()
    body = data.get("body", "").strip()
    include_paylink = data.get("includePayLink", False)
    use_discord = data.get("discord", False)
    use_email = data.get("email", False)
    use_sms = data.get("sms", False)

    # ── Load configuration
    cfg = configparser.ConfigParser()
    cfg.read(os.path.join("config", "config.ini"), encoding="utf-8")

    paypal_base = cfg.get("PayPal", "PaymentBaseLink", fallback="").rstrip("/")
    discord_enabled = cfg.getboolean("Discord", "Enabled", fallback=True)
    email_enabled = cfg.getboolean("SMTP", "Enabled", fallback=False)
    sms_enabled = cfg.getboolean("SMS", "Enabled", fallback=False)

    if not any([use_discord, use_email, use_sms]):
        return jsonify({"ok": False, "error": "No channels selected."}), 400

    # ── Retrieve target(s)
    recipients = []
    if target == "all":
        recipients = get_all_members()
    if groups:
        recipients = [r for r in recipients if (r[11] or '').lower() in groups]

    if not recipients:
        return jsonify({"ok": False, "error": "No matching members found."}), 404

    sent_summary = []
    for member in recipients:
        # Adapt to your DB schema
        discord_id = member[0]
        first_name = member[2] if len(member) > 2 else ""
        last_name = member[3] if len(member) > 3 else ""
        email = member[4] if len(member) > 4 else ""
        mobile = member[5] if len(member) > 5 else ""

        message_text = body
        if include_paylink and paypal_base:
            message_text += f"\n\n💳 Pay Now: {paypal_base}/{discord_id}"

        sent_channels = []

        # ───────────── Discord ─────────────
        if discord_enabled and use_discord:
            try:
                member_obj = None
                for g in bot.guilds:
                    m_obj = g.get_member(int(discord_id))
                    if m_obj:
                        member_obj = m_obj
                        break
                if member_obj:
                    asyncio.run_coroutine_threadsafe(
                        member_obj.send(f"**{subject}**\n\n{message_text}"), bot.loop
                    )
                    sent_channels.append("Discord")
            except Exception as e:
                print(f"⚠️ Discord DM failed for {discord_id}: {e}")

        # ───────────── Email ─────────────
        if email_enabled and use_email and email:
            try:
                send_email(subject, message_text, to=email)
                sent_channels.append("Email")
            except Exception as e:
                print(f"⚠️ Email send failed for {email}: {e}")

        # ───────────── SMS ─────────────
        if sms_enabled and use_sms and mobile:
            try:
                send_sms(mobile, message_text)
                sent_channels.append("SMS")
            except Exception as e:
                print(f"⚠️ SMS send failed for {mobile}: {e}")

        if sent_channels:
            sent_summary.append(
                {"member": f"{first_name} {last_name}".strip() or discord_id, "channels": sent_channels}
            )

    print(f"📢 Sent {len(sent_summary)} messages via unified system.")
    for s in sent_summary:
        print(f" → {s['member']}: {', '.join(s['channels'])}")

    return jsonify({
        "ok": True,
        "sent_count": len(sent_summary),
        "sent_via": [s["channels"] for s in sent_summary],
    })


@webui.route("/api/paylink/<member_id>", methods=["GET"])
def api_paylink(member_id):
    """Return a personalized PayPal payment link."""
    cfg = configparser.ConfigParser()
    cfg.read(os.path.join("config", "config.ini"), encoding="utf-8")
    base_link = cfg.get("PayPal", "PaymentBaseLink", fallback="").rstrip("/")
    if not base_link:
        return jsonify({"ok": False, "error": "PayPal PaymentBaseLink not set."}), 400
    return jsonify({"ok": True, "link": f"{base_link}/{member_id}"})

# ───────────────────────────────
# Reports
# ───────────────────────────────
@webui.route("/reports")
def reports():
    return render_template("reports.html", title="Reports | Casharr")

@webui.route("/api/report/summary")
def api_report_summary():
    rows = get_all_members()
    now = datetime.now(timezone.utc)

    def parse_iso_safe(dt):
        if not dt: return None
        try: return datetime.fromisoformat(dt)
        except Exception: return None

    total = len(rows)
    trials = sum(1 for r in rows if parse_iso_safe(r[8]) and parse_iso_safe(r[8]) > now)
    payers = sum(1 for r in rows if parse_iso_safe(r[10]) and parse_iso_safe(r[10]) > now)
    expired = sum(
        1 for r in rows
        if (parse_iso_safe(r[8]) and parse_iso_safe(r[8]) < now)
        or (parse_iso_safe(r[10]) and parse_iso_safe(r[10]) < now)
    )
    preview = sorted(rows, key=lambda r: str(r[0]))[-10:]
    members = [{"tag": r[1], "email": r[4], "trial_end": r[8], "paid_until": r[10], "referrer": r[14]} for r in preview]
    return jsonify({"total": total, "trials": trials, "payers": payers, "expired": expired, "members": members})

@webui.route("/api/report/ggenerate")  # (kept your route name typo out of caution)
@webui.route("/api/report/generate")
def api_generate_report():
    try:
        rows = get_all_members()
        if not rows:
            return jsonify({"success": False, "message": "No members found in database."})
        timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")

        pdf_path = os.path.join(EXPORTS_DIR, f"members_report_{timestamp}.pdf")
        doc = SimpleDocTemplate(pdf_path, pagesize=letter)
        styles = getSampleStyleSheet()
        elements = [
            Paragraph("Casharr Member Report", styles["Heading1"]),
            Spacer(1, 12),
            Paragraph(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles["Normal"]),
            Spacer(1, 12)
        ]

        total = len(rows)
        trials = sum(1 for r in rows if r[8])
        payers = sum(1 for r in rows if r[10])
        expired = total - trials - payers
        elements += [
            Paragraph(f"Total Members: <b>{total}</b>", styles["Normal"]),
            Paragraph(f"Active Trials: <b>{trials}</b>", styles["Normal"]),
            Paragraph(f"Active Payers: <b>{payers}</b>", styles["Normal"]),
            Paragraph(f"Expired: <b>{expired}</b>", styles["Normal"]),
            Spacer(1, 10), Paragraph("Details", styles["Heading2"]), Spacer(1, 6)
        ]

        data = [["Discord Tag", "Email", "Trial End", "Paid Until", "Referrer"]]
        for r in rows:
            data.append([r[1] or "-", r[4] or "-", r[8] or "-", r[10] or "-", r[14] or "-"])
        table = Table(data, repeatRows=1)
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.gray),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, -1), 'CENTER'),
            ('GRID', (0, 0), (-1, -1), 0.25, colors.black),
        ]))
        elements.append(table)
        doc.build(elements)

        xml_path = os.path.join(EXPORTS_DIR, f"members_report_{timestamp}.xml")
        root = ET.Element("MembersReport")
        ET.SubElement(root, "GeneratedAt").text = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for r in rows:
            m = ET.SubElement(root, "Member")
            ET.SubElement(m, "DiscordTag").text = r[1] or ""
            ET.SubElement(m, "Email").text = r[4] or ""
            ET.SubElement(m, "TrialEnd").text = r[8] or ""
            ET.SubElement(m, "PaidUntil").text = r[10] or ""
            ET.SubElement(m, "Referrer").text = r[14] or ""
        ET.ElementTree(root).write(xml_path, encoding="utf-8", xml_declaration=True)

        return jsonify({"success": True, "message": "✅ Report generated successfully.",
                        "pdf": os.path.basename(pdf_path), "xml": os.path.basename(xml_path)})
    except Exception as e:
        return jsonify({"success": False, "message": f"⚠️ Failed to generate report: {e}"})


@webui.route("/api/report/latest")
def api_latest_report():
    pdfs = sorted(glob.glob(os.path.join(EXPORTS_DIR, "members_report_*.pdf")))
    if not pdfs:
        return jsonify({"success": False, "message": "No reports found."})
    latest = pdfs[-1]
    return send_from_directory(EXPORTS_DIR, os.path.basename(latest), as_attachment=True)

# ─────────────────────────────
# Dashboard connection-status API
# ─────────────────────────────
@webui.route("/api/connection_status")
def api_connection_status():
    try:
        discord_online = getattr(bot, "is_ready", lambda: False)()
        plex_connected = False
        try:
            _ = plex.plex.friendlyName
            plex_connected = True
        except Exception:
            plex_connected = False
        return jsonify({"discord_online": discord_online, "plex_connected": plex_connected})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ─────────────────────────────
# Schema + Next Backup API
# ─────────────────────────────
def _read_schema_version():
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute("SELECT version FROM schema_version LIMIT 1")
        row = c.fetchone()
        conn.close()
        return row[0] if row else None
    except Exception:
        return None

def _compute_next_backup_time():
    """Infer next backup as (latest auto_backup_*.db mtime + 24h)."""
    try:
        files = sorted(glob.glob(os.path.join(EXPORTS_DIR, "auto_backup_*.db")))
        if not files:
            return None
        latest = max(files, key=lambda p: os.path.getmtime(p))
        next_ts = os.path.getmtime(latest) + 24*3600
        return datetime.fromtimestamp(next_ts).isoformat(sep=" ", timespec="seconds")
    except Exception:
        return None

@webui.route("/api/schema")
def api_schema():
    return jsonify({
        "schema_version": _read_schema_version(),
        "next_backup": _compute_next_backup_time()
    })

# ─────────────────────────────
# System Section Pages
# ─────────────────────────────
@webui.route("/system/status")
def system_status():
    return render_template("system_status.html", title="System | Status")

@webui.route("/system/tasks")
def system_tasks():
    return render_template("system_tasks.html", title="System | Tasks")

@webui.route("/system/backup")
def system_backup():
    backups = []
    for f in sorted(os.listdir(EXPORTS_DIR), reverse=True):
        if f.endswith(".db") or f.endswith(".zip"):
            path = os.path.join(EXPORTS_DIR, f)
            stat = os.stat(path)
            backups.append({
                "name": f,
                "size": f"{stat.st_size / (1024 * 1024):.1f} MiB",
                "date": datetime.fromtimestamp(stat.st_mtime).strftime("%b %d %Y %H:%M"),
            })
    return render_template("system_backup.html", title="System | Backup", backups=backups)

@webui.route("/system/backup_now")
def backup_now():
    ts = datetime.now().strftime("%Y.%m.%d_%H.%M.%S")
    out = os.path.join(EXPORTS_DIR, f"casharr_backup_{ts}.db")
    shutil.copy2(DB_PATH, out)
    return f"✅ Backup created: {os.path.basename(out)}"

@webui.route("/system/restore/<fname>", methods=["POST"])
def restore_backup(fname):
    path = os.path.join(EXPORTS_DIR, fname)
    if not os.path.exists(path):
        return "❌ File not found", 404
    shutil.copy2(path, DB_PATH)
    return f"✅ Database restored from {fname}"

@webui.route("/system/restore_upload", methods=["POST"])
def restore_upload():
    file = request.files.get("file")
    if not file:
        return "❌ No file selected"
    upload_path = os.path.join(EXPORTS_DIR, file.filename)
    file.save(upload_path)
    shutil.copy2(upload_path, DB_PATH)
    return f"✅ Database restored from uploaded file: {file.filename}"

@webui.route("/system/delete/<fname>", methods=["POST"])
def delete_backup(fname):
    path = os.path.join(EXPORTS_DIR, fname)
    if os.path.exists(path):
        os.remove(path)
        return f"🗑 Deleted {fname}"
    return "❌ File not found"

@webui.route("/system/logs")
def system_logs():
    logs = []
    for file in sorted(os.listdir(LOG_DIR), key=lambda f: os.path.getmtime(os.path.join(LOG_DIR, f)), reverse=True):
        if file.endswith(".log"):
            path = os.path.join(LOG_DIR, file)
            with open(path, "r", encoding="utf-8", errors="ignore") as f:
                content = f.read()
            logs.append({
                "name": file,
                "content": content or "(empty file)",
                "mtime": datetime.fromtimestamp(os.path.getmtime(path)).strftime("%Y-%m-%d %H:%M"),
            })
    if not logs:
        logs = [{"name": "No logs found", "content": "Logs will appear once Casharr runs."}]
    return render_template("system_logs.html", title="System | Log Files", logs=logs)

@webui.route("/system/logs/download/<filename>")
def download_log(filename):
    safe_path = os.path.join(LOG_DIR, filename)
    if not os.path.exists(safe_path):
        abort(404)
    return send_from_directory(LOG_DIR, filename, as_attachment=True)

@webui.route("/system/updates")
def system_updates():
    repo = "AquillaComputingSystem/Casharr"
    api_url = f"https://api.github.com/repos/{repo}/releases"
    local_version = "Unknown"
    try:
        with open("VERSION", "r", encoding="utf-8") as f:
            local_version = f.read().strip()
    except FileNotFoundError:
        local_version = "Unknown"

    try:
        res = requests.get(api_url, timeout=5)
        if res.status_code == 200:
            releases = res.json()[:5]
            updates = [{
                "version": r.get("tag_name", "Unknown"),
                "name": r.get("name", "No title"),
                "body": r.get("body", "No changelog available."),
                "url": r.get("html_url", "#"),
                "date": r.get("published_at", "Unknown"),
            } for r in releases]

            latest_remote = updates[0]["version"] if updates else "Unknown"
            status = None
            if local_version != "Unknown" and latest_remote != "Unknown":
                status = "up_to_date" if local_version == latest_remote else "outdated"

            return render_template(
                "system_updates.html",
                title="System | Updates",
                updates=updates,
                local_version=local_version,
                latest_version=latest_remote,
                status=status,
            )
        else:
            return render_template(
                "system_updates.html",
                title="System | Updates",
                error=f"GitHub API error: {res.status_code}",
                local_version=local_version,
            )
    except Exception as e:
        return render_template(
            "system_updates.html",
            title="System | Updates",
            error=str(e),
            local_version=local_version,
        )

@webui.route("/system/events")
def system_events():
    return render_template("system_events.html", title="System | Events")

# ─────────────────────────────
# System Status API (used by /system/status)
# ─────────────────────────────
_start_time = time.time()

@webui.route("/api/status")
def api_status():
    try:
        discord_online = getattr(bot, "is_ready", lambda: False)()
        plex_connected = False
        if plex is not None:
            try:
                plex_connected = plex.test_connection()
            except AttributeError:
                try:
                    _ = plex.plex.friendlyName
                    plex_connected = True
                except Exception:
                    plex_connected = False

        disk = psutil.disk_usage("/")
        disk_info = {
            "total": f"{disk.total / (1024**3):.1f} GB",
            "used": f"{disk.used / (1024**3):.1f} GB",
            "percent": disk.percent,
        }
        uptime = str(timedelta(seconds=int(time.time() - _start_time)))
        return jsonify({
            "discord_online": discord_online,
            "plex_connected": plex_connected,
            "uptime": uptime,
            "disk": disk_info
        })
    except Exception as e:
        return jsonify({"error": str(e)}), 500

# ─────────────────────────────
# Events API (log parse)
# ─────────────────────────────
@webui.route("/api/events")
def api_events():
    try:
        log_files = sorted(glob.glob(os.path.join(LOG_DIR, "*.log")), reverse=True)
        if not log_files:
            return jsonify({"events": []})
        latest_log = log_files[0]
        with open(latest_log, "r", encoding="utf-8", errors="ignore") as f:
            lines = f.readlines()[-300:]
        events = []
        for line in lines:
            if any(kw in line for kw in ["Joined", "Payment", "Removed", "Trial", "Referral", "Promo", "Error"]):
                try:
                    ts = line.split(" [")[0]
                    msg = line.strip()
                    events.append({"time": ts, "message": msg})
                except Exception:
                    continue
        events = list(reversed(events[-100:]))
        return jsonify({"events": events})
    except Exception as e:
        return jsonify({"error": str(e), "events": []})

# ─────────────────────────────
# TASKS: list + run endpoints (System > Tasks)
# ─────────────────────────────
def _maintenance_cleanup():
    """Lightweight maintenance: remove orphan/empty records and vacuum; zip logs."""
    try:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        # Example cleanup: remove rows with no trial & no paid_until
        c.execute("DELETE FROM members WHERE (trial_end IS NULL OR trial_end='') AND (paid_until IS NULL OR paid_until='')")
        conn.execute("VACUUM")
        conn.close()
        # archive logs
        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        shutil.make_archive(os.path.join(EXPORTS_DIR, f"logs_backup_{ts}"), "zip", LOG_DIR)
        return True, "Maintenance complete."
    except Exception as e:
        return False, str(e)

def _create_manual_backup():
    ts = datetime.now().strftime("%Y.%m.%d_%H.%M.%S")
    out = os.path.join(EXPORTS_DIR, f"casharr_backup_{ts}.db")
    shutil.copy2(DB_PATH, out)
    return out

@webui.route("/api/tasks")
def api_tasks():
    """Return a simple task registry for the UI table."""
    # infer next backup time from latest auto backup + 24h
    next_backup = _compute_next_backup_time()
    tasks = [
        {"name": "Maintenance", "interval": "On demand", "last_execution": None, "last_duration": None, "next_execution": None, "running": False},
        {"name": "Manual Backup", "interval": "On demand", "last_execution": None, "last_duration": None, "next_execution": None, "running": False},
        {"name": "Auto Backup", "interval": "Every 24h", "last_execution": None, "last_duration": None, "next_execution": next_backup, "running": False},
        {"name": "Reminders", "interval": "Scheduled", "last_execution": None, "last_duration": None, "next_execution": None, "running": False},
        {"name": "Enforce Access", "interval": "Scheduled", "last_execution": None, "last_duration": None, "next_execution": None, "running": False},
        {"name": "Audit Plex", "interval": "Scheduled", "last_execution": None, "last_duration": None, "next_execution": None, "running": False},
    ]
    return jsonify({"ok": True, "tasks": tasks})

@webui.route("/api/tasks/run", methods=["POST"])
def api_tasks_run():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").lower()

    if "maintenance" in name:
        ok, msg = _maintenance_cleanup()
        return jsonify({"ok": ok, "message": msg})

    if "backup" in name:
        try:
            path = _create_manual_backup()
            return jsonify({"ok": True, "message": f"Backup created: {os.path.basename(path)}"})
        except Exception as e:
            return jsonify({"ok": False, "error": str(e)})

    return jsonify({"ok": False, "error": "Unknown task."})

# ─────────────────────────────
# SMTP Test Endpoint (plain text)
# ─────────────────────────────
@webui.route("/apo/test_email", methods=["POST"])
def api_test_email():
    try:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        send_email("Casharr SMTP Test", f"Casharr SMTP test successful at {now}.")
        return jsonify({"ok": True, "message": "Test email sent."})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

# ─────────────────────────────
# SMS Test Endpoint
# ─────────────────────────────
@webui.route("/api/test_sms", methods=["POST"])
def api_test_sms():
    try:
        from helpers.sms import send_sms
        CONFIG_PATH = os.path.join("config", "config.ini")
        cfg = configparser.ConfigParser()
        cfg.read(CONFIG_PATH, encoding="utf-8")
        test_number = cfg.get("SMS", "TestNumber", fallback="").strip()

        if not test_number:
            return jsonify({"ok": False, "error": "No TestNumber configured in [SMS]."}), 400

        success = send_sms(test_number, "Casharr SMS test successful ✅")
        if not success:
            return jsonify({"ok": False, "error": "SMS gateway did not respond or failed."}), 500

        return jsonify({"ok": True, "message": "✅ Test SMS sent successfully."})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500
