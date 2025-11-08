import os
import sqlite3
from datetime import datetime, timezone, timedelta

# ─────────────────────────────
# Database Path (Persistent)
# ─────────────────────────────
os.makedirs("data", exist_ok=True)
DB_PATH = os.path.join("data", "members.db")

# ─────────────────────────────
# Schema Version Tracking
# ─────────────────────────────
SCHEMA_VERSION = 1  # bump this when database structure changes

def ensure_version_table(conn):
    """Ensure schema_version table exists and insert default version."""
    c = conn.cursor()
    c.execute("CREATE TABLE IF NOT EXISTS schema_version (version INTEGER)")
    c.execute("SELECT version FROM schema_version")
    row = c.fetchone()
    if not row:
        c.execute("INSERT INTO schema_version VALUES (?)", (SCHEMA_VERSION,))
    conn.commit()

# ─────────────────────────────
# Initialization
# ─────────────────────────────
def init_db():
    """Create or upgrade the members table."""
    conn = sqlite3.connect(DB_PATH)
    ensure_version_table(conn)
    c = conn.cursor()
    c.execute("""
        CREATE TABLE IF NOT EXISTS members (
            discord_id TEXT PRIMARY KEY,
            discord_tag TEXT,
            first_name TEXT,
            last_name TEXT,
            email TEXT,
            mobile TEXT,
            invite_sent_at TEXT,
            trial_start TEXT,
            trial_end TEXT,
            had_trial INTEGER DEFAULT 0,
            paid_until TEXT,
            trial_reminder_sent_at TEXT,
            paid_reminder_sent_at TEXT,
            used_promo INTEGER DEFAULT 0,
            referrer_id TEXT,
            is_referrer INTEGER DEFAULT 0,
            referral_paid INTEGER DEFAULT 0,
            origin TEXT DEFAULT NULL   -- 'invite' or 'sync'
        )
    """)

    # Add any missing columns automatically
    new_columns = [
        ("origin", "TEXT DEFAULT NULL"),
    ]
    for col_name, col_def in new_columns:
        try:
            c.execute(f"ALTER TABLE members ADD COLUMN {col_name} {col_def}")
        except Exception:
            pass
    # Add any missing columns automatically
    new_columns = [
        ("referrer_id", "TEXT"),
        ("is_referrer", "INTEGER DEFAULT 0"),
        ("referral_paid", "INTEGER DEFAULT 0"),
        ("origin", "TEXT DEFAULT NULL")
    ]
    for col_name, col_def in new_columns:
        try:
            c.execute(f"ALTER TABLE members ADD COLUMN {col_name} {col_def}")
        except Exception:
            pass


    conn.commit()
    conn.close()

# ─────────────────────────────
# Member Operations
# ─────────────────────────────
def save_member(discord_id, first_name="", last_name="", email="", mobile="", discord_tag="", origin="invite"):
    """Insert or update a member’s basic info."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        INSERT INTO members (discord_id, discord_tag, first_name, last_name, email, mobile, origin)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(discord_id) DO UPDATE SET
            discord_tag=excluded.discord_tag,
            first_name=excluded.first_name,
            last_name=excluded.last_name,
            email=excluded.email,
            mobile=excluded.mobile,
            origin=COALESCE(members.origin, excluded.origin)
    """, (str(discord_id), discord_tag, first_name, last_name, email, mobile, origin))
    conn.commit()
    conn.close()


def set_referrer(discord_id, referrer_id):
    """Record who referred a member and mark the referrer as active."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE members SET referrer_id=? WHERE discord_id=?", (str(referrer_id), str(discord_id)))
    c.execute("UPDATE members SET is_referrer=1 WHERE discord_id=?", (str(referrer_id),))
    conn.commit()
    conn.close()


def mark_referral_paid(referrer_id):
    """Mark that the referrer has received referral credit."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE members SET referral_paid=1 WHERE discord_id=?", (str(referrer_id),))
    conn.commit()
    conn.close()


def update_invite_sent(discord_id):
    """Record timestamp when Plex invite was sent."""
    now = datetime.now(timezone.utc).isoformat()
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE members SET invite_sent_at=? WHERE discord_id=?", (now, str(discord_id)))
    conn.commit()
    conn.close()


def start_trial(discord_id, duration_days):
    """Start a trial period for a member."""
    now = datetime.now(timezone.utc)
    end = now + timedelta(days=duration_days)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        UPDATE members
        SET trial_start=?, trial_end=?, had_trial=1
        WHERE discord_id=?
    """, (now.isoformat(), end.isoformat(), str(discord_id)))
    conn.commit()
    conn.close()


def end_trial(discord_id):
    """End the trial immediately."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE members SET trial_end=NULL WHERE discord_id=?", (str(discord_id),))
    conn.commit()
    conn.close()


def clear_trial_after_payment(discord_id):
    """Clear trial info once a payment is recorded."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("UPDATE members SET trial_end=NULL WHERE discord_id=?", (str(discord_id),))
    conn.commit()
    conn.close()


def update_payment(discord_id, months):
    """Extend paid access by a given number of months and clear any active trial."""
    import configparser, requests
    from plexhelper import PlexHelper

    now = datetime.now(timezone.utc)
    added = timedelta(days=30 * int(months))
    existing = get_member(discord_id)
    base = now

    if existing and existing[10]:  # paid_until
        try:
            current_paid = datetime.fromisoformat(existing[10])
            if current_paid > now:
                base = current_paid
        except Exception:
            pass

    new_paid_until = base + added

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        UPDATE members
        SET paid_until=?, trial_end=NULL
        WHERE discord_id=?
    """, (new_paid_until.isoformat(), str(discord_id)))
    conn.commit()
    conn.close()

    # Optional webhook admin log
    CONFIG_PATH = os.path.join("config", "config.ini")
    cfg = configparser.ConfigParser()
    if os.path.exists(CONFIG_PATH):
        cfg.read(CONFIG_PATH)
        webhook = cfg["Discord"].get("AdminWebhookURL", "").strip()
        if webhook:
            msg = (
                f"💳 Payment recorded for <@{discord_id}> — "
                f"trial cleared and access extended to {new_paid_until.date()}."
            )
            try:
                requests.post(webhook, json={"content": msg}, timeout=5)
            except Exception:
                pass

# ─────────────────────────────
# Reminder Helpers
# ─────────────────────────────
def mark_trial_reminder_sent(discord_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "UPDATE members SET trial_reminder_sent_at=? WHERE discord_id=?",
        (datetime.now(timezone.utc).isoformat(), str(discord_id)),
    )
    conn.commit()
    conn.close()


def mark_paid_reminder_sent(discord_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        "UPDATE members SET paid_reminder_sent_at=? WHERE discord_id=?",
        (datetime.now(timezone.utc).isoformat(), str(discord_id)),
    )
    conn.commit()
    conn.close()

# ─────────────────────────────
# Promo Helpers
# ─────────────────────────────
def mark_promo_used(discord_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE members SET used_promo=1 WHERE discord_id=?", (str(discord_id),))
    conn.commit()
    conn.close()


def has_used_promo(discord_id):
    row = get_member(discord_id)
    return bool(row and len(row) > 13 and row[13] == 1)


def is_promo_eligible(discord_id):
    """
    FINAL POLICY:
    - Only brand-new members created via an invite (origin='invite') are eligible.
    - No promo for synced members, active trials, or current payers.
    - One-time only; once used_promo=1, blocked permanently.
    """
    row = get_member(discord_id)
    if not row:
        return True  # New member → eligible

    origin = None
    try:
        origin = row[17] if len(row) > 17 else None
    except Exception:
        pass

    # Must come from invite (not sync/manual)
    if origin != "invite":
        return False

    # Already used promo → no
    if has_used_promo(discord_id):
        return False

    # Active trial or payment → no
    paid_until = row[10]
    trial_end = row[8]

    now = datetime.now(timezone.utc)
    try:
        if paid_until and datetime.fromisoformat(paid_until) > now:
            return False
    except Exception:
        pass
    try:
        if trial_end and datetime.fromisoformat(trial_end) > now:
            return False
    except Exception:
        pass

    return True

# ─────────────────────────────
# Referral Helpers
# ─────────────────────────────
def get_referrals(referrer_id):
    """Return list of members referred by this user."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT discord_id, discord_tag FROM members WHERE referrer_id=?", (str(referrer_id),))
    rows = c.fetchall()
    conn.close()
    return rows


def get_referrer(discord_id):
    """Return the referrer for a given member (if any)."""
    row = get_member(discord_id)
    if row and len(row) > 14 and row[14]:
        return row[14]
    return None

# ─────────────────────────────
# Query Functions
# ─────────────────────────────
def get_all_members():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM members")
    rows = c.fetchall()
    conn.close()
    return rows


def get_member(discord_id):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT discord_id, discord_tag, first_name, last_name, email, mobile,
               invite_sent_at, trial_start, trial_end, had_trial,
               paid_until, trial_reminder_sent_at, paid_reminder_sent_at,
               used_promo, referrer_id, is_referrer, referral_paid, origin
        FROM members WHERE discord_id=?
    """, (str(discord_id),))
    row = c.fetchone()
    conn.close()
    return row


def get_trial_members():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT discord_id, email, trial_end FROM members WHERE trial_end IS NOT NULL")
    rows = c.fetchall()
    conn.close()
    return rows


def get_payer_members():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT discord_id, email, paid_until FROM members WHERE paid_until IS NOT NULL")
    rows = c.fetchall()
    conn.close()
    return rows


def get_all_for_reminders():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT discord_id, email, trial_end, paid_until, trial_reminder_sent_at, paid_reminder_sent_at
        FROM members
    """)
    rows = c.fetchall()
    conn.close()
    return rows


def has_active_trial(discord_id):
    row = get_member(discord_id)
    if not row:
        return False
    trial_end = row[8]
    if not trial_end:
        return False
    try:
        end_dt = datetime.fromisoformat(trial_end)
        return end_dt > datetime.now(timezone.utc)
    except Exception:
        return False
# ───────────────────────────────────────────────
# 🧩 Additional Helpers for WebUI CRUD Endpoints
# ───────────────────────────────────────────────

import sqlite3
from datetime import datetime

def add_or_update_member(discord_id, email="", trial_end=None, paid_until=None, role="Trial", referrer=None):
    """
    Insert or update a member record. If the discord_id exists, update the row.
    """
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    # Ensure date formatting
    trial_end = trial_end or ""
    paid_until = paid_until or ""
    now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    # Try to update if exists, else insert
    c.execute("""
        SELECT id FROM members WHERE discord_id = ?
    """, (discord_id,))
    existing = c.fetchone()

    if existing:
        c.execute("""
            UPDATE members
            SET email=?, trial_end=?, paid_until=?, role=?, referrer=?, last_update=?
            WHERE discord_id=?
        """, (email, trial_end, paid_until, role, referrer, now, discord_id))
    else:
        c.execute("""
            INSERT INTO members (discord_id, email, trial_end, paid_until, role, referrer, created_at, last_update)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (discord_id, email, trial_end, paid_until, role, referrer, now, now))

    conn.commit()
    conn.close()


def delete_member(member_id):
    """Remove a member by ID."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM members WHERE id = ?", (member_id,))
    conn.commit()
    conn.close()


def update_member_role(member_id, role):
    """Update a member's role (Trial, Payer, Lifetime, etc)."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        UPDATE members
        SET role=?, last_update=?
        WHERE id=?
    """, (role, datetime.now().strftime("%Y-%m-%d %H:%M:%S"), member_id))
    conn.commit()
    conn.close()

# ─────────────────────────────
# Initialize Database
# ─────────────────────────────
init_db()
