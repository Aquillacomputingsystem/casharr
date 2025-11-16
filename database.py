import os
import sqlite3
import configparser
from datetime import datetime, timezone, timedelta
import secrets

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
            origin TEXT DEFAULT NULL,   -- 'invite' or 'sync'
            discord_roles TEXT DEFAULT NULL
        )
    """)

    # Add any missing columns automatically
    new_columns = [
        ("origin", "TEXT DEFAULT NULL"),
        ("discord_roles", "TEXT DEFAULT NULL"),
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
        ("origin", "TEXT DEFAULT NULL"),
        ("discord_roles", "TEXT DEFAULT NULL"),
    ]
    for col_name, col_def in new_columns:
        try:
            c.execute(f"ALTER TABLE members ADD COLUMN {col_name} {col_def}")
        except Exception:
            pass
# Plex username column
    new_columns = [
        ("plex_username", "TEXT")
    ]
    for col_name, col_def in new_columns:
        try:
            c.execute(f"ALTER TABLE members ADD COLUMN {col_name} {col_def}")
        except Exception:
            pass
    # ───── Onboarding columns ─────
    new_columns = [
        ("join_token", "TEXT"),
        ("join_status", "TEXT DEFAULT 'pending'"),
    ]
    for col_name, col_def in new_columns:
        try:
            c.execute(f"ALTER TABLE members ADD COLUMN {col_name} {col_def}")
        except Exception:
            pass


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

def clear_all_trial_fields(discord_id: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        UPDATE members
        SET trial_start=NULL,
            trial_end=NULL,
            had_trial=0,
            trial_reminder_sent_at=NULL
        WHERE discord_id=?
    """, (discord_id,))
    conn.commit()
    conn.close()

def clear_paid_until(discord_id: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        UPDATE members
        SET paid_until=NULL
        WHERE discord_id=?
    """, (discord_id,))
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

    # Start from "now" by default
    base = now

    # Safely look up existing paid_until using get_member() dict
    existing = get_member(discord_id)
    paid_until = existing.get("paid_until") if existing else None

    if paid_until:
        try:
            current_paid = datetime.fromisoformat(paid_until)
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
    return bool(row and row.get("used_promo") == 1)


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
        origin = row.get("origin")
    except Exception:
        pass

    # Must come from invite (not sync/manual)
    if origin != "invite":
        return False

    # Already used promo → no
    if has_used_promo(discord_id):
        return False

    # Active trial or payment → no
    paid_until = row.get("paid_until")
    trial_end = row.get("trial_end")

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
    if row and row.get("referrer_id"):
        return row.get("referrer_id")

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

    # Fetch *all* columns including plex_username
    c.execute("PRAGMA table_info(members)")
    cols = [row[1] for row in c.fetchall()]

    # Select columns dynamically
    c.execute(f"SELECT {', '.join(cols)} FROM members WHERE discord_id=?", (str(discord_id),))
    row = c.fetchone()

    conn.close()
    return dict(zip(cols, row)) if row else None

def get_member_by_email(email: str):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM members WHERE lower(email)=lower(?)", (email,))
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
    """Return all members eligible for trial or paid reminders."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
        SELECT discord_id, email, mobile, trial_end, paid_until,
               trial_reminder_sent_at, paid_reminder_sent_at
        FROM members
        WHERE (trial_end IS NOT NULL AND trial_end != '')
           OR (paid_until IS NOT NULL AND paid_until != '')
    """)
    rows = c.fetchall()
    conn.close()
    return rows


def has_active_trial(discord_id):
    row = get_member(discord_id)
    if not row:
        return False

    trial_end = row.get("trial_end")
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

def _configured_trial_days(default: int = 30) -> int:
    """Read the default trial duration from config.ini (fallback to 30)."""
    cfg = configparser.ConfigParser()
    try:
        cfg.read(os.path.join("config", "config.ini"), encoding="utf-8")
        return cfg.getint("Trial", "DurationDays", fallback=default)
    except Exception:
        return default

def save_member(
    discord_id=None,
    discord_tag="",
    first_name="",
    last_name="",
    email="",
    mobile="",
    origin="manual",
    roles=None,
    status=None,
):
    """
    Create or update a member record.
    - Matches on discord_id or email.
    - If discord_id is missing, creates a placeholder 'plex:<email>'.
    - Never overwrites an existing status/roles unless explicitly provided.
    """

    # Normalize fields
    discord_id = str(discord_id or "").strip()
    email = str(email or "").strip().lower()
    roles_value = None
    if roles:
        roles_value = ", ".join(roles) if isinstance(roles, (list, tuple)) else str(roles)

    # Placeholder for Plex-only users
    if not discord_id:
        discord_id = f"plex:{email}" if email else secrets.token_hex(4)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Check existing record
    c.execute("""
        SELECT discord_id, status, discord_roles
        FROM members
        WHERE discord_id=? OR (email IS NOT NULL AND lower(email)=lower(?))
    """, (discord_id, email))
    existing = c.fetchone()

    if existing:
        current_id, current_status, current_roles = existing
        print(f"[save_member] Updating existing {email or discord_id}")
        c.execute("""
    UPDATE members
    SET discord_id = COALESCE(NULLIF(?, ''), discord_id),
        discord_tag = COALESCE(NULLIF(?, ''), discord_tag),
        first_name  = COALESCE(NULLIF(?, ''), first_name),
        last_name   = COALESCE(NULLIF(?, ''), last_name),
        email       = COALESCE(NULLIF(?, ''), email),
        mobile      = COALESCE(NULLIF(?, ''), mobile),
        origin      = COALESCE(origin, ?),
        status      = COALESCE(?, status),
        discord_roles = COALESCE(?, discord_roles)
    WHERE discord_id=? OR (email IS NOT NULL AND lower(email)=lower(?))
""", (
    discord_id,            # NEW — updates the old plex:xxx ID
    discord_tag,
    first_name,
    last_name,
    email,
    mobile,
    origin,
    status or current_status,
    roles_value or current_roles,
    current_id,            # IMPORTANT: match the existing row
    email
))
    else:
        print(f"[save_member] Inserting new {email or discord_id}")
        c.execute("""
            INSERT INTO members (
                discord_id, discord_tag, first_name, last_name, email, mobile,
                origin, status, discord_roles
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            discord_id, discord_tag, first_name, last_name, email, mobile,
            origin, status, roles_value
        ))

    conn.commit()
    conn.close()

def delete_member(discord_id=None, email=None):
    """
    Forcefully remove a member record — by Discord ID, email, or both.
    If both are missing, it deletes any placeholder or orphan rows with blank IDs/emails.
    Returns True if any rows were deleted.
    """
    with sqlite3.connect(DB_PATH) as conn:
        c = conn.cursor()

        # Try delete by Discord ID first (if valid)
        if discord_id and discord_id not in ("", "None", None, "noid"):
            c.execute("DELETE FROM members WHERE discord_id = ?", (discord_id,))
        # Then try by email (if valid)
        elif email and email not in ("", "None", None):
            c.execute("DELETE FROM members WHERE email = ?", (email,))
        # Fallback — delete orphans (no ID and no email)
        else:
            c.execute("DELETE FROM members WHERE (discord_id IS NULL OR discord_id = '' OR discord_id = 'noid') "
                      "AND (email IS NULL OR email = '')")

        conn.commit()
        return c.rowcount > 0

    
def update_member_role(discord_id, role: str):
    """Update database state based on a human-readable role selection."""
    if not discord_id:
        raise ValueError("discord_id is required")
    if not role:
        raise ValueError("role is required")

    normalized = role.strip().lower()

    if normalized == "no access":
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        c.execute(
            "UPDATE members SET trial_start=NULL, trial_end=NULL, paid_until=NULL WHERE discord_id=?",
            (str(discord_id),),
        )
        conn.commit()
        conn.close()
        return

    if normalized == "trial":
        days = _configured_trial_days()
        start_trial(discord_id, days)
        return

    if normalized == "payer":
        update_payment(discord_id, 1)
        return

    if normalized == "lifetime":
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        far_future = datetime.now(timezone.utc) + timedelta(days=365 * 100)
        c.execute(
            "UPDATE members SET paid_until=?, trial_end=NULL WHERE discord_id=?",
            (far_future.isoformat(), str(discord_id)),
        )
        conn.commit()
        conn.close()
        return

    raise ValueError(f"Unsupported role '{role}'")

def generate_join_token(discord_id: str) -> str:
    """Generate or return existing onboarding token for a member."""
    token = secrets.token_urlsafe(12)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("UPDATE members SET join_token=?, join_status='pending' WHERE discord_id=?", (token, str(discord_id)))
    if c.rowcount == 0:
        c.execute("INSERT INTO members (discord_id, join_token, join_status) VALUES (?, ?, 'pending')",
                  (str(discord_id), token))
    conn.commit()
    conn.close()
    return token


def get_member_by_token(token: str):
    """Look up a member record from its join token."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT * FROM members WHERE join_token=?", (token,))
    row = c.fetchone()
    conn.close()
    return row

def generate_referral_token(referrer_id: str) -> str:
    """Generate or reuse a referral token tied to an existing member."""
    import secrets
    token = secrets.token_urlsafe(12)
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Verify the referrer exists
    c.execute("SELECT discord_id FROM members WHERE discord_id=?", (str(referrer_id),))
    if not c.fetchone():
        conn.close()
        raise ValueError(f"Referrer {referrer_id} not found in members table")

    # Create new pending invite linked to the referrer
    c.execute("""
        INSERT INTO members (join_token, join_status, referrer_id)
        VALUES (?, 'pending', ?)
    """, (token, str(referrer_id)))
    conn.commit()
    conn.close()
    return token

def apply_referral_bonus(referrer_id: str, new_member_id: str, referral_cfg, trial_cfg):
    """Apply referral rewards based on config.ini Referral & Trial sections."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # Load base durations and bonuses
    base_days = int(trial_cfg.get("durationdays", 30))
    referral_bonus = int(referral_cfg.get("bonus1month", 7))  # Default fallback

    try:
        # 1️⃣ Extend the new member's trial
        c.execute("SELECT trial_end FROM members WHERE discord_id=?", (new_member_id,))
        row = c.fetchone()
        if row and row[0]:
            c.execute("UPDATE members SET trial_end = date(trial_end, ? || ' days') WHERE discord_id=?",
                      (referral_bonus, new_member_id))
        else:
            c.execute("UPDATE members SET trial_end = date('now', ? || ' days') WHERE discord_id=?",
                      (base_days + referral_bonus, new_member_id))

        # 2️⃣ Extend the referrer's paid_until or trial_end
        c.execute("SELECT paid_until, trial_end FROM members WHERE discord_id=?", (referrer_id,))
        ref_row = c.fetchone()
        if ref_row:
            if ref_row[0]:
                c.execute("UPDATE members SET paid_until = date(paid_until, ? || ' days') WHERE discord_id=?",
                          (referral_bonus, referrer_id))
            elif ref_row[1]:
                c.execute("UPDATE members SET trial_end = date(trial_end, ? || ' days') WHERE discord_id=?",
                          (referral_bonus, referrer_id))

        conn.commit()
    except Exception as e:
        print(f"⚠️ Referral bonus error: {e}")
    finally:
        conn.close()

# ───────────────────────────────
# MARK PAID / EXTEND TRIAL HELPERS
# ───────────────────────────────
import sqlite3
from datetime import datetime, timedelta

def update_paid_until(discord_id: str, days: int = 30):
    """Extend or set paid_until date for a member."""
    db_path = os.path.join("data", "members.db")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("SELECT paid_until FROM members WHERE discord_id = ?", (discord_id,))
    row = cur.fetchone()
    now = datetime.now()
    new_date = now + timedelta(days=days)

    if row and row[0]:
        try:
            current_date = datetime.fromisoformat(row[0])
            if current_date > now:
                new_date = current_date + timedelta(days=days)
        except Exception:
            pass

    cur.execute("UPDATE members SET paid_until = ? WHERE discord_id = ?", (new_date.isoformat(), discord_id))
    conn.commit()
    conn.close()
    return new_date.isoformat()


def extend_trial(discord_id: str, days: int = 7):
    """Extend or set trial_end date for a member."""
    db_path = os.path.join("data", "members.db")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    cur.execute("SELECT trial_end FROM members WHERE discord_id = ?", (discord_id,))
    row = cur.fetchone()
    now = datetime.now()
    new_date = now + timedelta(days=days)

    if row and row[0]:
        try:
            current_date = datetime.fromisoformat(row[0])
            if current_date > now:
                new_date = current_date + timedelta(days=days)
        except Exception:
            pass

    cur.execute("UPDATE members SET trial_end = ? WHERE discord_id = ?", (new_date.isoformat(), discord_id))
    conn.commit()
    conn.close()
    return new_date.isoformat()

def update_member_status(discord_id: str, new_status: str):
    """Update the status of a member (Trial, Payer, Lifetime, Expired)."""
    db_path = os.path.join("data", "members.db")
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    cur.execute("UPDATE members SET status = ? WHERE discord_id = ?", (new_status, discord_id))
    print(f"🟢 Updated {discord_id} to {new_status}")
    conn.commit()
    conn.close()
    return True

def ensure_schema():
    """Ensure members table has all required columns and that pending_actions and plex_username exist."""
    db_path = os.path.join("data", "members.db")
    conn = sqlite3.connect(db_path)
    c = conn.cursor()

    # ─────────────────────────────
    # Ensure 'status' column exists in members
    # ─────────────────────────────
    c.execute("PRAGMA table_info(members);")
    columns = [r[1] for r in c.fetchall()]
    if "status" not in columns:
        c.execute("ALTER TABLE members ADD COLUMN status TEXT;")
        conn.commit()
        print("🆕 Added 'status' column to members table (no default).")
        conn.commit()
        print("🆕 Added 'status' column to members table.")

    # ─────────────────────────────
    # Ensure 'plex_username' column exists in members
    # ─────────────────────────────
    c.execute("PRAGMA table_info(members);")
    columns = [r[1] for r in c.fetchall()]
    if "plex_username" not in columns:
        c.execute("ALTER TABLE members ADD COLUMN plex_username TEXT;")
        conn.commit()
        print("🆕 Added 'plex_username' column to members table.")

    # ─────────────────────────────
    # Ensure 'pending_actions' table exists
    # ─────────────────────────────
    c.execute("""
        CREATE TABLE IF NOT EXISTS pending_actions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            discord_id TEXT,
            email TEXT,
            proposed_status TEXT,
            reason TEXT,
            detected_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()

    conn.close()


def add_pending_action(discord_id, email, proposed_status, reason):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("INSERT INTO pending_actions (discord_id, email, proposed_status, reason) VALUES (?, ?, ?, ?)",
              (discord_id, email, proposed_status, reason))
    conn.commit(); conn.close()

def get_pending_actions():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT id, discord_id, email, proposed_status, reason, detected_at FROM pending_actions")
    rows = c.fetchall(); conn.close()
    return rows

def resolve_pending_action(action_id, approve: bool):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    if approve:
        # Apply status update
        row = c.execute("SELECT discord_id, proposed_status FROM pending_actions WHERE id=?", (action_id,)).fetchone()
        if row:
            update_member_role(row[0], row[1])
    c.execute("DELETE FROM pending_actions WHERE id=?", (action_id,))
    conn.commit(); conn.close()

def add_or_update_member(**kwargs):
    save_member(**kwargs)

# ─────────────────────────────
# Initialize Database
# ─────────────────────────────
init_db()
ensure_schema()