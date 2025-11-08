import os
import sqlite3
import configparser
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
            origin TEXT DEFAULT NULL,   -- 'invite' or 'sync'
            discord_roles TEXT DEFAULT NULL
        )
    """)

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
    c.execute(
        """
        CREATE TABLE IF NOT EXISTS detail_requests (
            discord_id TEXT PRIMARY KEY,
            step INTEGER NOT NULL DEFAULT 0,
            first_name TEXT,
            last_name TEXT,
            email TEXT,
            mobile TEXT,
            intro_sent INTEGER NOT NULL DEFAULT 0,
            origin TEXT,
            roles TEXT,
            discord_tag TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )

    conn.commit()
    conn.close()

# ─────────────────────────────
# Member Operations
# ─────────────────────────────
def _connect_row():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def save_member(
    discord_id,
    first_name="",
    last_name="",
    email="",
    mobile="",
    discord_tag="",
    origin="invite",
    roles=None,
):
    """Insert or update a member’s basic info."""

    roles_value = None
    if roles is not None:
        if isinstance(roles, str):
            roles_value = roles.strip()
        else:
            cleaned = []
            for item in roles:
                text = str(item).strip()
                if text:
                    cleaned.append(text)
            roles_value = ", ".join(cleaned)

    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(
        """
        INSERT INTO members (
            discord_id,
            discord_tag,
            first_name,
            last_name,
            email,
            mobile,
            origin,
            discord_roles
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(discord_id) DO UPDATE SET
            discord_tag=excluded.discord_tag,
            first_name=excluded.first_name,
            last_name=excluded.last_name,
            email=excluded.email,
            mobile=excluded.mobile,
            origin=COALESCE(members.origin, excluded.origin),
            discord_roles=COALESCE(excluded.discord_roles, members.discord_roles)
    """,
        (
            str(discord_id),
            discord_tag,
            first_name,
            last_name,
            email,
            mobile,
            origin,
            roles_value,
        ),
    )
    conn.commit()
    conn.close()


def get_detail_request(discord_id):
    """Fetch a pending detail request record as a dict, or None."""
    conn = _connect_row()
    cur = conn.cursor()
    cur.execute(
        "SELECT discord_id, step, first_name, last_name, email, mobile, intro_sent, origin, roles, discord_tag, created_at, updated_at FROM detail_requests WHERE discord_id=?",
        (str(discord_id),),
    )
    row = cur.fetchone()
    conn.close()
    return dict(row) if row else None


def list_detail_requests():
    """Return all pending detail request records."""
    conn = _connect_row()
    cur = conn.cursor()
    cur.execute(
        "SELECT discord_id, step, first_name, last_name, email, mobile, intro_sent, origin, roles, discord_tag, created_at, updated_at FROM detail_requests"
    )
    rows = cur.fetchall()
    conn.close()
    return [dict(row) for row in rows]


def save_detail_request_state(discord_id, **fields):
    """Insert or update a pending detail request, returning the stored state."""
    now = datetime.now(timezone.utc).isoformat()
    existing = get_detail_request(discord_id)

    state = {
        "discord_id": str(discord_id),
        "step": 0,
        "first_name": "",
        "last_name": "",
        "email": "",
        "mobile": "",
        "intro_sent": 0,
        "origin": "",
        "roles": "",
        "discord_tag": "",
        "created_at": now,
        "updated_at": now,
    }

    if existing:
        state.update(existing)
        state["created_at"] = existing.get("created_at") or now

    for key, value in fields.items():
        if key in state:
            state[key] = value

    state["updated_at"] = now

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO detail_requests (
            discord_id, step, first_name, last_name, email, mobile, intro_sent, origin, roles, discord_tag, created_at, updated_at
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(discord_id) DO UPDATE SET
            step=excluded.step,
            first_name=excluded.first_name,
            last_name=excluded.last_name,
            email=excluded.email,
            mobile=excluded.mobile,
            intro_sent=excluded.intro_sent,
            origin=excluded.origin,
            roles=excluded.roles,
            discord_tag=excluded.discord_tag,
            updated_at=excluded.updated_at
        """,
        (
            state["discord_id"],
            state["step"],
            state["first_name"],
            state["last_name"],
            state["email"],
            state["mobile"],
            int(state["intro_sent"]),
            state["origin"],
            state["roles"],
            state["discord_tag"],
            state["created_at"],
            state["updated_at"],
        ),
    )
    conn.commit()
    conn.close()
    return state


def delete_detail_request(discord_id):
    """Remove a pending detail request, if any."""
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("DELETE FROM detail_requests WHERE discord_id=?", (str(discord_id),))
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
               used_promo, referrer_id, is_referrer, referral_paid, origin, discord_roles
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

def _configured_trial_days(default: int = 30) -> int:
    """Read the default trial duration from config.ini (fallback to 30)."""
    cfg = configparser.ConfigParser()
    try:
        cfg.read(os.path.join("config", "config.ini"), encoding="utf-8")
        return cfg.getint("Trial", "DurationDays", fallback=default)
    except Exception:
        return default


def add_or_update_member(
    discord_id,
    *,
    discord_tag="",
    first_name="",
    last_name="",
    email="",
    mobile="",
    origin="manual",
):
    """Upsert the core member fields used by the WebUI."""
    if not discord_id:
        raise ValueError("discord_id is required")

    save_member(
        discord_id=str(discord_id),
        first_name=first_name,
        last_name=last_name,
        email=email,
        mobile=mobile,
        discord_tag=discord_tag,
        origin=origin,
    )


def delete_member(discord_id) -> bool:
    """Remove a member by Discord ID. Returns True if a row was deleted."""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DELETE FROM members WHERE discord_id = ?", (str(discord_id),))
    deleted = c.rowcount
    conn.commit()
    conn.close()
    return deleted > 0


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

# ─────────────────────────────
# Initialize Database
# ─────────────────────────────
init_db()
